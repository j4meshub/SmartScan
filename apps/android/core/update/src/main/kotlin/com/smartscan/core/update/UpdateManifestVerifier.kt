package com.smartscan.core.update

import java.io.File
import java.net.URI
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class UpdateManifest(
    @SerialName("schema_version") val schemaVersion: Int,
    @SerialName("package_name") val packageName: String,
    @SerialName("version_code") val versionCode: Long,
    @SerialName("version_name") val versionName: String,
    @SerialName("minimum_supported_version_code") val minimumSupportedVersionCode: Long,
    @SerialName("apk_url") val apkUrl: String,
    @SerialName("apk_sha256") val apkSha256: String,
    @SerialName("apk_signing_certificate_sha256") val apkSigningCertificateSha256: String,
    @SerialName("published_at") val publishedAt: String,
)

data class VerifiedUpdate(
    val manifest: UpdateManifest,
    val mandatory: Boolean,
)

sealed interface UpdateVerificationResult {
    data class Available(val update: VerifiedUpdate) : UpdateVerificationResult
    data object Current : UpdateVerificationResult
    data class Rejected(val reason: String) : UpdateVerificationResult
}

class UpdateManifestVerifier(
    publicKeyBase64: String,
    private val json: Json = Json { ignoreUnknownKeys = true; explicitNulls = false },
) {
    private val publicKey = KeyFactory.getInstance("Ed25519").generatePublic(
        X509EncodedKeySpec(Base64.getDecoder().decode(publicKeyBase64)),
    )

    fun verify(
        payload: ByteArray,
        signatureBase64: String,
        expectedPackageName: String,
        currentVersionCode: Long,
    ): UpdateVerificationResult = runCatching {
        val signature = Signature.getInstance("Ed25519")
        signature.initVerify(publicKey)
        signature.update(payload)
        require(signature.verify(Base64.getDecoder().decode(signatureBase64))) { "manifest_signature_invalid" }
        val manifest = json.decodeFromString<UpdateManifest>(payload.decodeToString())
        require(manifest.schemaVersion == 1) { "manifest_schema_unsupported" }
        require(manifest.packageName == expectedPackageName) { "package_name_mismatch" }
        require(manifest.versionCode > 0 && manifest.minimumSupportedVersionCode > 0) { "version_code_invalid" }
        require(manifest.versionName.isNotBlank() && manifest.publishedAt.isNotBlank()) { "manifest_field_missing" }
        require(manifest.apkSha256.matches(SHA256)) { "apk_hash_invalid" }
        require(manifest.apkSigningCertificateSha256.matches(SHA256)) { "certificate_hash_invalid" }
        val apkUri = URI(manifest.apkUrl)
        require(apkUri.scheme.equals("https", ignoreCase = true) && apkUri.host != null) { "apk_url_invalid" }
        require(apkUri.userInfo == null && apkUri.fragment == null) { "apk_url_credential_invalid" }
        if (manifest.versionCode <= currentVersionCode) {
            UpdateVerificationResult.Current
        } else {
            UpdateVerificationResult.Available(
                VerifiedUpdate(manifest, mandatory = currentVersionCode < manifest.minimumSupportedVersionCode),
            )
        }
    }.getOrElse { UpdateVerificationResult.Rejected(it.message ?: "manifest_invalid") }

    companion object {
        private val SHA256 = Regex("^[a-f0-9]{64}$")
    }
}

fun verifyApkSha256(file: File, expectedSha256: String): Boolean {
    if (!file.isFile || !expectedSha256.matches(Regex("^[a-f0-9]{64}$"))) return false
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
    }
    val actual = digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    return MessageDigest.isEqual(actual.toByteArray(), expectedSha256.toByteArray())
}
