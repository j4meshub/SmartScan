package com.smartscan.feature.update

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.core.content.pm.PackageInfoCompat
import com.smartscan.core.update.ApkPackageIdentity
import com.smartscan.core.update.UpdateManifest
import com.smartscan.core.update.UpdateManifestVerifier
import com.smartscan.core.update.UpdateVerificationResult
import com.smartscan.core.update.VerifiedUpdate
import com.smartscan.core.update.verifyApkPackageIdentity
import com.smartscan.core.update.verifyApkSha256
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

sealed interface UpdateCheckResult {
    data object NotDue : UpdateCheckResult
    data object Current : UpdateCheckResult
    data class Available(val update: VerifiedUpdate) : UpdateCheckResult
    data class Failed(val reason: String) : UpdateCheckResult
}

sealed interface UpdateDownloadResult {
    data class Ready(val file: File, val update: VerifiedUpdate) : UpdateDownloadResult
    data class Failed(val reason: String) : UpdateDownloadResult
}

enum class InstallLaunchResult { INSTALLER_OPENED, PERMISSION_OPENED, REJECTED }

class AndroidUpdateManager private constructor(
    private val context: Context,
    private val manifestUrl: String,
    private val signatureUrl: String,
    private val verifier: UpdateManifestVerifier,
    private val client: OkHttpClient,
    private val clock: () -> Long,
) {
    private val preferences = context.getSharedPreferences("smartscan-update", Context.MODE_PRIVATE)
    private val updateRoot = File(context.cacheDir, "updates").canonicalFile

    suspend fun check(force: Boolean = false): UpdateCheckResult = withContext(Dispatchers.IO) {
        val now = clock()
        val previous = preferences.getLong(LAST_CHECK_AT, 0L)
        if (!force && !shouldCheckForUpdate(previous, now)) return@withContext UpdateCheckResult.NotDue
        runCatching {
            val payload = fetch(manifestUrl, MAX_MANIFEST_BYTES)
            val signature = fetch(signatureUrl, MAX_SIGNATURE_BYTES).decodeToString().trim()
            when (val result = verifier.verify(payload, signature, context.packageName, installedVersionCode())) {
                UpdateVerificationResult.Current -> UpdateCheckResult.Current
                is UpdateVerificationResult.Available -> UpdateCheckResult.Available(result.update)
                is UpdateVerificationResult.Rejected -> UpdateCheckResult.Failed(result.reason)
            }.also {
                if (it !is UpdateCheckResult.Failed) preferences.edit().putLong(LAST_CHECK_AT, now).apply()
            }
        }.getOrElse { UpdateCheckResult.Failed(stableFailure(it)) }
    }

    suspend fun download(update: VerifiedUpdate): UpdateDownloadResult = withContext(Dispatchers.IO) {
        runCatching {
            require(updateRoot.mkdirs() || updateRoot.isDirectory) { "update_directory_unavailable" }
            val destination = File(updateRoot, "SmartScan-${update.manifest.versionCode}.apk").canonicalFile
            require(destination.parentFile == updateRoot) { "update_path_invalid" }
            val temporary = File(updateRoot, ".${destination.name}.part")
            temporary.delete()
            try {
                downloadApk(update.manifest, temporary)
                val identityFailure = verifyArchive(temporary, update.manifest)
                require(identityFailure == null) { identityFailure ?: "apk_identity_invalid" }
                if (destination.exists() && !destination.delete()) throw IOException("update_replace_failed")
                if (!temporary.renameTo(destination)) throw IOException("update_commit_failed")
                UpdateDownloadResult.Ready(destination, update)
            } catch (failure: Exception) {
                temporary.delete()
                throw failure
            }
        }.getOrElse { UpdateDownloadResult.Failed(stableFailure(it)) }
    }

    fun launchInstaller(activity: Activity, ready: UpdateDownloadResult.Ready): InstallLaunchResult {
        val file = runCatching { ready.file.canonicalFile }.getOrNull() ?: return InstallLaunchResult.REJECTED
        if (!file.isFile || file.parentFile != updateRoot) return InstallLaunchResult.REJECTED
        if (file.length() != ready.update.manifest.apkSizeBytes) return InstallLaunchResult.REJECTED
        if (!verifyApkSha256(file, ready.update.manifest.apkSha256)) return InstallLaunchResult.REJECTED
        if (verifyArchive(file, ready.update.manifest) != null) return InstallLaunchResult.REJECTED
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
            return runCatching {
                activity.startActivity(
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")),
                )
                InstallLaunchResult.PERMISSION_OPENED
            }.getOrDefault(InstallLaunchResult.REJECTED)
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        return runCatching {
            activity.startActivity(
                Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, APK_MIME_TYPE)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                },
            )
            InstallLaunchResult.INSTALLER_OPENED
        }.getOrDefault(InstallLaunchResult.REJECTED)
    }

    private fun downloadApk(manifest: UpdateManifest, temporary: File) {
        val request = Request.Builder().url(manifest.apkUrl).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("update_http_${response.code}")
            require(response.request.url.isHttps) { "update_url_invalid" }
            val body = response.body ?: throw IOException("update_body_missing")
            val declared = body.contentLength()
            require(declared < 0 || declared == manifest.apkSizeBytes) { "apk_size_mismatch" }
            val digest = MessageDigest.getInstance("SHA-256")
            var written = 0L
            body.byteStream().use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        written += count
                        require(written <= manifest.apkSizeBytes) { "apk_size_mismatch" }
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                    }
                }
            }
            require(written == manifest.apkSizeBytes) { "apk_size_mismatch" }
            val actual = digest.digest().toHex()
            require(MessageDigest.isEqual(actual.toByteArray(), manifest.apkSha256.toByteArray())) { "apk_hash_mismatch" }
        }
    }

    private fun verifyArchive(file: File, manifest: UpdateManifest): String? {
        val archive = context.packageManager.archiveIdentity(file) ?: return "apk_metadata_unavailable"
        val installed = context.packageManager.installedIdentity(context.packageName) ?: return "installed_metadata_unavailable"
        return verifyApkPackageIdentity(manifest, archive, installed)
    }

    private fun installedVersionCode(): Long =
        context.packageManager.installedIdentity(context.packageName)?.versionCode ?: error("installed_metadata_unavailable")

    private fun fetch(url: String, maximumBytes: Long): ByteArray {
        val request = Request.Builder().url(url).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("update_http_${response.code}")
            require(response.request.url.isHttps) { "update_url_invalid" }
            val body = response.body ?: throw IOException("update_body_missing")
            require(body.contentLength() < 0 || body.contentLength() <= maximumBytes) { "update_response_too_large" }
            val output = ByteArrayOutputStream()
            body.byteStream().use { input ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                var written = 0L
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    written += count
                    require(written <= maximumBytes) { "update_response_too_large" }
                    output.write(buffer, 0, count)
                }
            }
            return output.toByteArray()
        }
    }

    companion object {
        fun createOrNull(
            context: Context,
            manifestUrl: String,
            signatureUrl: String,
            publicKeyBase64: String,
            client: OkHttpClient = OkHttpClient.Builder()
                .followRedirects(false)
                .followSslRedirects(false)
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .build(),
            clock: () -> Long = System::currentTimeMillis,
        ): AndroidUpdateManager? {
            if (!isValidUpdateConfiguration(manifestUrl, signatureUrl, publicKeyBase64)) return null
            return runCatching {
                AndroidUpdateManager(
                    context.applicationContext,
                    manifestUrl,
                    signatureUrl,
                    UpdateManifestVerifier(publicKeyBase64),
                    client,
                    clock,
                )
            }.getOrNull()
        }

        private const val LAST_CHECK_AT = "last_check_at"
        private const val MAX_MANIFEST_BYTES = 128L * 1024
        private const val MAX_SIGNATURE_BYTES = 4096L
        private const val APK_MIME_TYPE = "application/vnd.android.package-archive"
    }
}

internal fun shouldCheckForUpdate(lastCheckAt: Long, now: Long): Boolean =
    lastCheckAt <= 0 || now < lastCheckAt || now - lastCheckAt >= TimeUnit.DAYS.toMillis(1)

internal fun isValidUpdateConfiguration(
    manifestUrl: String,
    signatureUrl: String,
    publicKeyBase64: String,
): Boolean {
    if (manifestUrl.isBlank() || signatureUrl.isBlank() || publicKeyBase64.isBlank()) return false
    if (!isSafeHttpsUrl(manifestUrl) || !isSafeHttpsUrl(signatureUrl)) return false
    return runCatching { UpdateManifestVerifier(publicKeyBase64) }.isSuccess
}

private fun isSafeHttpsUrl(value: String): Boolean = runCatching {
    val uri = URI(value)
    uri.scheme.equals("https", ignoreCase = true) && uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null
}.getOrDefault(false)

@Suppress("DEPRECATION")
private fun PackageManager.archiveIdentity(file: File): ApkPackageIdentity? =
    getPackageArchiveInfo(file.absolutePath, signatureFlags())?.toIdentity()

@Suppress("DEPRECATION")
private fun PackageManager.installedIdentity(packageName: String): ApkPackageIdentity? = runCatching {
    getPackageInfo(packageName, signatureFlags()).toIdentity()
}.getOrNull()

private fun signatureFlags(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
    PackageManager.GET_SIGNING_CERTIFICATES
} else {
    @Suppress("DEPRECATION")
    PackageManager.GET_SIGNATURES
}

@Suppress("DEPRECATION")
private fun PackageInfo.toIdentity(): ApkPackageIdentity {
    val signers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        signingInfo?.apkContentsSigners.orEmpty().map { it.toByteArray() }
    } else {
        signatures.orEmpty().map { it.toByteArray() }
    }
    return ApkPackageIdentity(
        packageName = packageName,
        versionCode = PackageInfoCompat.getLongVersionCode(this),
        signerSha256s = signers.map { MessageDigest.getInstance("SHA-256").digest(it).toHex() }.toSet(),
    )
}

private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xff) }
private fun stableFailure(error: Throwable): String = error.message?.takeIf { it.matches(Regex("^[a-z0-9_]+$")) } ?: "update_failed"
