package com.smartscan.data.repository

import com.smartscan.core.model.DownloadedArtifact
import com.smartscan.core.model.ExportArtifact
import com.smartscan.core.model.ProjectExport
import com.smartscan.core.model.ScanProject
import com.smartscan.core.model.ScanPage
import com.smartscan.core.network.ExportCreateRequestDto
import com.smartscan.core.network.ExportDto
import com.smartscan.core.network.PageCornerDto
import com.smartscan.core.network.PageEditRequestDto
import com.smartscan.core.network.PageOrderRequestDto
import com.smartscan.core.network.PageReviewRequestDto
import com.smartscan.core.network.PageRotationRequestDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ScanApi
import com.smartscan.core.network.WorkspaceApi
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import retrofit2.HttpException

interface ProjectRepository {
    suspend fun listProjects(): ApiResult<List<ScanProject>>
    suspend fun listPages(projectId: String): ApiResult<List<ScanPage>>
    suspend fun reorderPages(projectId: String, pageIds: List<String>): ApiResult<List<ScanPage>>
    suspend fun rotatePage(pageId: String, degrees: Int): ApiResult<ScanPage>
    suspend fun editPage(pageId: String, corners: List<Pair<Double, Double>>, filter: String): ApiResult<ScanPage>
    suspend fun reviewPage(pageId: String, confirmed: Boolean): ApiResult<ScanPage>
    suspend fun createExport(
        projectId: String,
        format: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport>
    suspend fun refreshExport(exportId: String): ApiResult<ProjectExport>
    suspend fun downloadPagePreview(pageId: String, directory: File): ApiResult<DownloadedArtifact>
    suspend fun downloadExportArtifact(artifact: ExportArtifact, directory: File): ApiResult<DownloadedArtifact>
}

class DefaultProjectRepository(
    private val api: ScanApi,
    private val workspaceApi: WorkspaceApi? = null,
    private val cache: UserScopedCache? = null,
    private val currentUserId: () -> String? = { null },
) : ProjectRepository {
    override suspend fun listProjects(): ApiResult<List<ScanProject>> {
        val userId = currentUserId()
        return when (val remote = safeApiCall { api.listProjects().map { it.toModel() } }) {
            is ApiResult.Success -> {
                if (userId != null) runCatching { cache?.replaceProjects(userId, remote.value) }
                remote
            }
            is ApiResult.Failure -> {
                val cached = if (userId == null) null else runCatching { cache?.listProjects(userId) }.getOrNull()
                if (!cached.isNullOrEmpty()) ApiResult.Success(cached) else remote
            }
        }
    }

    override suspend fun listPages(projectId: String): ApiResult<List<ScanPage>> = withWorkspace {
        api.listPages(projectId).map { it.toModel() }
    }

    override suspend fun reorderPages(projectId: String, pageIds: List<String>): ApiResult<List<ScanPage>> = withWorkspace {
        require(pageIds.isNotEmpty() && pageIds.size == pageIds.toSet().size) { "page_order_invalid" }
        it.reorderPages(projectId, PageOrderRequestDto(pageIds)).map { page -> page.toModel() }
    }

    override suspend fun rotatePage(pageId: String, degrees: Int): ApiResult<ScanPage> = withWorkspace {
        require(degrees in setOf(90, 180, 270)) { "rotation_invalid" }
        it.rotatePage(pageId, PageRotationRequestDto(degrees)).toModel()
    }

    override suspend fun editPage(
        pageId: String,
        corners: List<Pair<Double, Double>>,
        filter: String,
    ): ApiResult<ScanPage> = withWorkspace {
        require(corners.size == 4 && corners.all { (x, y) -> x in 0.0..1.0 && y in 0.0..1.0 }) { "corners_invalid" }
        require(filter in setOf("original", "enhance", "grayscale", "bw")) { "filter_invalid" }
        it.editPage(pageId, PageEditRequestDto(corners.map { (x, y) -> PageCornerDto(x, y) }, filter)).toModel()
    }

    override suspend fun reviewPage(pageId: String, confirmed: Boolean): ApiResult<ScanPage> = withWorkspace {
        it.reviewPage(pageId, PageReviewRequestDto(if (confirmed) "confirmed" else "pending")).toModel()
    }

    override suspend fun createExport(
        projectId: String,
        format: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport> = withWorkspace {
        require(format in setOf("jpg", "pdf")) { "export_format_invalid" }
        require(quality in setOf("clear", "balanced", "small")) { "export_quality_invalid" }
        it.createExport(projectId, ExportCreateRequestDto(format, quality, includeOcrText)).toModel()
    }

    override suspend fun refreshExport(exportId: String): ApiResult<ProjectExport> = withWorkspace {
        it.getExport(exportId).toModel()
    }

    override suspend fun downloadPagePreview(pageId: String, directory: File): ApiResult<DownloadedArtifact> = withWorkspace {
        withContext(Dispatchers.IO) {
            val stableName = "page-${sha256(pageId.toByteArray()).take(16)}.img"
            saveDownload(it.downloadPageContent(pageId), directory, stableName, null, null)
        }
    }

    override suspend fun downloadExportArtifact(
        artifact: ExportArtifact,
        directory: File,
    ): ApiResult<DownloadedArtifact> = withWorkspace {
        withContext(Dispatchers.IO) {
            saveDownload(
                body = it.downloadExportArtifact(artifact.id),
                directory = directory,
                requestedName = "${artifact.id.take(12)}-${artifact.fileName}",
                displayName = artifact.fileName,
                expectedSha256 = artifact.sha256,
                fallbackMimeType = artifact.mimeType,
                expectedSize = artifact.sizeBytes,
            )
        }
    }

    private suspend fun <T> withWorkspace(block: suspend (WorkspaceApi) -> T): ApiResult<T> {
        val endpoint = workspaceApi ?: return ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
        return safeApiCall { block(endpoint) }
    }
}

private fun ProjectDto.toModel() = ScanProject(
    id = id,
    title = title,
    suggestedName = suggestedName,
    mode = mode,
    readingOrder = readingOrder,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun com.smartscan.core.network.PageDto.toModel() = ScanPage(
    id = id,
    projectId = projectId,
    pageNumber = pageNumber,
    reviewStatus = reviewStatus,
    qualityWarning = qualityWarning,
    activeResultVersion = activeResultVersion,
    ocrStatus = ocrStatus,
)

private fun ExportDto.toModel() = ProjectExport(
    id = id,
    projectId = projectId,
    format = format,
    quality = quality,
    includeOcrText = includeOcrText,
    status = status,
    pageCount = pageCount,
    errorCode = errorCode,
    artifacts = artifacts.map {
        ExportArtifact(it.id, it.pageId, it.sequence, it.fileName, it.mimeType, it.sha256, it.sizeBytes)
    },
    createdAt = createdAt,
)

private fun saveDownload(
    body: okhttp3.ResponseBody,
    directory: File,
    requestedName: String,
    displayName: String = requestedName,
    expectedSha256: String?,
    fallbackMimeType: String?,
    expectedSize: Long? = null,
): DownloadedArtifact {
    require(directory.mkdirs() || directory.isDirectory) { "download_directory_unavailable" }
    val safeName = File(requestedName).name.trim().takeIf { it.isNotEmpty() && it !in setOf(".", "..") }
        ?: throw IllegalArgumentException("download_name_invalid")
    val root = directory.canonicalFile
    val destination = File(root, safeName).canonicalFile
    require(destination.parentFile == root) { "download_path_invalid" }
    val temporary = File(root, ".${safeName}.${UUID.randomUUID()}.part")
    val digest = MessageDigest.getInstance("SHA-256")
    var written = 0L
    try {
        body.use { response ->
            response.byteStream().use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                        written += count
                    }
                }
            }
            expectedSize?.let { require(written == it) { "download_size_mismatch" } }
            expectedSha256?.let { require(digest.digest().toHex() == it) { "download_hash_mismatch" } }
            if (destination.exists() && !destination.delete()) throw IOException("download_replace_failed")
            if (!temporary.renameTo(destination)) throw IOException("download_commit_failed")
            return DownloadedArtifact(
                filePath = destination.absolutePath,
                fileName = File(displayName).name,
                mimeType = response.contentType()?.toString() ?: fallbackMimeType ?: "application/octet-stream",
            )
        }
    } catch (failure: Exception) {
        temporary.delete()
        throw failure
    }
}

private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).toHex()
private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xFF) }

internal suspend fun <T> safeApiCall(block: suspend () -> T): ApiResult<T> = try {
    ApiResult.Success(block())
} catch (error: HttpException) {
    val status = error.code()
    val kind = when (status) {
        401 -> FailureKind.UNAUTHORIZED
        404 -> FailureKind.NOT_FOUND
        429 -> FailureKind.RATE_LIMITED
        in 500..599 -> FailureKind.SERVER
        else -> FailureKind.UNKNOWN
    }
    ApiResult.Failure(kind, statusCode = status, retryable = status == 429 || status >= 500)
} catch (_: IOException) {
    ApiResult.Failure(FailureKind.NETWORK, retryable = true)
} catch (_: SerializationException) {
    ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
} catch (_: IllegalArgumentException) {
    ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
}
