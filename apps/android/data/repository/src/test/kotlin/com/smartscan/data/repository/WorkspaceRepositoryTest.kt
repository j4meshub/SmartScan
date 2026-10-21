package com.smartscan.data.repository

import com.smartscan.core.model.ExportArtifact
import com.smartscan.core.network.ExportCreateRequestDto
import com.smartscan.core.network.ExportDto
import com.smartscan.core.network.PageDto
import com.smartscan.core.network.PageEditRequestDto
import com.smartscan.core.network.PageOrderRequestDto
import com.smartscan.core.network.PageReviewRequestDto
import com.smartscan.core.network.PageRotationRequestDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ScanApi
import com.smartscan.core.network.WorkspaceApi
import java.nio.file.Path
import java.security.MessageDigest
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class WorkspaceRepositoryTest {
    @TempDir
    lateinit var temporaryDirectory: Path

    @Test
    fun `page edit validates corners and maps returned version`() = runTest {
        val workspace = FakeWorkspaceApi()
        val repository = DefaultProjectRepository(QueryApi(), workspace)

        val result = repository.editPage(
            "page-1",
            listOf(0.0 to 0.0, 1.0 to 0.0, 1.0 to 1.0, 0.0 to 1.0),
            "enhance",
        )

        assertEquals("enhance", workspace.lastEdit?.filter)
        assertEquals(4, workspace.lastEdit?.corners?.size)
        assertEquals(2, (result as ApiResult.Success).value.activeResultVersion)
    }

    @Test
    fun `page order rejects duplicates before network`() = runTest {
        val workspace = FakeWorkspaceApi()
        val repository = DefaultProjectRepository(QueryApi(), workspace)

        val result = repository.reorderPages("project-1", listOf("page-1", "page-1"))

        assertEquals(FailureKind.INVALID_RESPONSE, (result as ApiResult.Failure).kind)
        assertFalse(workspace.reorderCalled)
    }

    @Test
    fun `export download verifies size and sha before publishing file`() = runTest {
        val bytes = "verified-export".toByteArray()
        val workspace = FakeWorkspaceApi(downloadBytes = bytes)
        val repository = DefaultProjectRepository(QueryApi(), workspace)
        val artifact = ExportArtifact(
            id = "artifact-1",
            pageId = null,
            sequence = 1,
            fileName = "扫描结果.pdf",
            mimeType = "application/pdf",
            sha256 = sha256(bytes),
            sizeBytes = bytes.size.toLong(),
        )

        val result = repository.downloadExportArtifact(artifact, temporaryDirectory.toFile())

        val download = (result as ApiResult.Success).value
        assertEquals("扫描结果.pdf", download.fileName)
        assertTrue(Path.of(download.filePath).toFile().readBytes().contentEquals(bytes))
        assertTrue(temporaryDirectory.toFile().listFiles().orEmpty().none { it.name.endsWith(".part") })
    }

    @Test
    fun `hash mismatch removes temporary and final files`() = runTest {
        val bytes = "tampered".toByteArray()
        val repository = DefaultProjectRepository(QueryApi(), FakeWorkspaceApi(downloadBytes = bytes))
        val artifact = ExportArtifact(
            id = "artifact-1",
            pageId = null,
            sequence = 1,
            fileName = "result.pdf",
            mimeType = "application/pdf",
            sha256 = "0".repeat(64),
            sizeBytes = bytes.size.toLong(),
        )

        val result = repository.downloadExportArtifact(artifact, temporaryDirectory.toFile())

        assertEquals(FailureKind.INVALID_RESPONSE, (result as ApiResult.Failure).kind)
        assertTrue(temporaryDirectory.toFile().listFiles().orEmpty().isEmpty())
    }
}

private class QueryApi : ScanApi {
    override suspend fun createProject(request: com.smartscan.core.network.CreateProjectRequestDto): ProjectDto = error("not used")
    override suspend fun listProjects(): List<ProjectDto> = emptyList()
    override suspend fun listPages(projectId: String): List<PageDto> = listOf(page())
    override suspend fun listJobs() = emptyList<com.smartscan.core.network.JobDto>()
    override suspend fun listExports(projectId: String) = emptyList<ExportDto>()
    override suspend fun createUpload(request: com.smartscan.core.network.CreateUploadRequestDto) = error("not used")
    override suspend fun getUpload(uploadId: String) = error("not used")
    override suspend fun putUploadChunk(
        uploadId: String,
        chunkIndex: Int,
        chunkSha256: String,
        body: okhttp3.RequestBody,
    ) = error("not used")
    override suspend fun completeUpload(uploadId: String) = error("not used")
}

private class FakeWorkspaceApi(private val downloadBytes: ByteArray = "preview".toByteArray()) : WorkspaceApi {
    var lastEdit: PageEditRequestDto? = null
    var reorderCalled = false

    override suspend fun reorderPages(projectId: String, request: PageOrderRequestDto): List<PageDto> {
        reorderCalled = true
        return request.pageIds.mapIndexed { index, id -> page(id, index + 1) }
    }

    override suspend fun rotatePage(pageId: String, request: PageRotationRequestDto) = page(pageId)

    override suspend fun editPage(pageId: String, request: PageEditRequestDto): PageDto {
        lastEdit = request
        return page(pageId).copy(activeResultVersion = 2)
    }

    override suspend fun reviewPage(pageId: String, request: PageReviewRequestDto) =
        page(pageId).copy(reviewStatus = request.status)

    override suspend fun createExport(projectId: String, request: ExportCreateRequestDto) = export(projectId, request)
    override suspend fun getExport(exportId: String) = export("project-1", ExportCreateRequestDto("pdf"))
    override suspend fun downloadPageContent(pageId: String, variant: String) = downloadBytes.toResponseBody()
    override suspend fun downloadExportArtifact(artifactId: String) = downloadBytes.toResponseBody()
}

private fun page(id: String = "page-1", number: Int = 1) = PageDto(
    id = id,
    projectId = "project-1",
    pageNumber = number,
    qualityWarning = null,
    qualityDetails = null,
    activeResultVersion = 1,
    reviewStatus = "pending",
    ocrStatus = "completed",
)

private fun export(projectId: String, request: ExportCreateRequestDto) = ExportDto(
    id = "export-1",
    projectId = projectId,
    format = request.format,
    quality = request.quality,
    includeOcrText = request.includeOcrText,
    status = "completed",
    pageCount = 1,
    errorCode = null,
    artifacts = emptyList(),
    createdAt = "2026-10-21T00:00:00Z",
)

private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
    .digest(bytes)
    .joinToString("") { "%02x".format(it.toInt() and 0xFF) }
