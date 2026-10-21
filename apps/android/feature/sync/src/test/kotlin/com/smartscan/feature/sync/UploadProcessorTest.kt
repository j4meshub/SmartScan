package com.smartscan.feature.sync

import com.smartscan.core.network.ChunkReceiptDto
import com.smartscan.core.network.CreateProjectRequestDto
import com.smartscan.core.network.CreateUploadRequestDto
import com.smartscan.core.network.PageDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.UploadDto
import com.smartscan.core.upload.LocalUploadProject
import com.smartscan.core.upload.QueuedUpload
import com.smartscan.core.upload.UploadQueueStatus
import com.smartscan.core.upload.UploadQueueStore
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class UploadProcessorTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun `server confirmed chunks are skipped and remaining chunks complete`() = runTest {
        val fixture = fixture(receivedChunks = listOf(0))

        val result = UploadProcessor(fixture.remote, fixture.store).processProject("user-1", "local-1")

        assertEquals(UploadProcessResult.Success, result)
        assertEquals(listOf(1, 2), fixture.remote.sentChunks)
        assertEquals(UploadQueueStatus.COMPLETED, fixture.store.upload.status)
        assertEquals("page-1", fixture.store.upload.pageId)
    }

    @Test
    fun `network interruption keeps idempotency and requests retry`() = runTest {
        val fixture = fixture(receivedChunks = emptyList())
        fixture.remote.chunkFailure = IOException("offline")
        val originalKey = fixture.store.upload.idempotencyKey

        val result = UploadProcessor(fixture.remote, fixture.store).processProject("user-1", "local-1")

        assertEquals(UploadProcessResult.Retry, result)
        assertEquals(UploadQueueStatus.RETRYING, fixture.store.upload.status)
        assertEquals(originalKey, fixture.store.upload.idempotencyKey)
    }

    @Test
    fun `expired session rotates idempotency before retry`() = runTest {
        val fixture = fixture(receivedChunks = emptyList(), uploadStatus = "expired")
        val originalKey = fixture.store.upload.idempotencyKey

        val result = UploadProcessor(fixture.remote, fixture.store).processProject("user-1", "local-1")

        assertEquals(UploadProcessResult.Retry, result)
        assertNotEquals(originalKey, fixture.store.upload.idempotencyKey)
        assertEquals(null, fixture.store.upload.serverUploadId)
    }

    @Test
    fun `missing local file is permanent failure`() = runTest {
        val fixture = fixture(receivedChunks = emptyList())
        fixture.store.upload = fixture.store.upload.copy(localPath = temporaryFolder.root.resolve("missing.jpg").absolutePath)

        val result = UploadProcessor(fixture.remote, fixture.store).processProject("user-1", "local-1")

        assertEquals(UploadProcessResult.Failed, result)
        assertEquals(UploadQueueStatus.FAILED, fixture.store.upload.status)
        assertEquals("local_file_missing", fixture.store.upload.errorCode)
    }

    private fun fixture(receivedChunks: List<Int>, uploadStatus: String = "active"): Fixture {
        val source = temporaryFolder.newFile("original-${System.nanoTime()}.jpg")
        source.writeBytes(ByteArray(10) { it.toByte() })
        val store = FakeStore(
            project = LocalUploadProject("user-1", "local-1", "扫描", "document", null),
            upload = QueuedUpload(
                ownerUserId = "user-1",
                id = "queue-1",
                localProjectId = "local-1",
                localPath = source.absolutePath,
                fileName = source.name,
                mimeType = "image/jpeg",
                sizeBytes = source.length(),
                sha256 = null,
                idempotencyKey = "idempotency-key-1",
                serverUploadId = null,
                uploadedBytes = 0,
                status = UploadQueueStatus.QUEUED,
                pageId = null,
                errorCode = null,
                createdAtEpochMs = 1,
            ),
        )
        return Fixture(store, FakeRemote(receivedChunks, uploadStatus))
    }
}

private data class Fixture(val store: FakeStore, val remote: FakeRemote)

private class FakeRemote(
    private val receivedChunks: List<Int>,
    private val uploadStatus: String,
) : UploadRemote {
    val sentChunks = mutableListOf<Int>()
    var chunkFailure: Exception? = null

    override suspend fun createProject(request: CreateProjectRequestDto) = ProjectDto(
        id = "server-project",
        ownerUserId = "user-1",
        title = request.title,
        suggestedName = null,
        suggestedNameSource = null,
        mode = request.mode,
        readingOrder = request.readingOrder,
        createdAt = "2026-10-20T00:00:00Z",
        updatedAt = "2026-10-20T00:00:00Z",
    )

    override suspend fun createUpload(request: CreateUploadRequestDto) = UploadDto(
        id = "server-upload",
        projectId = request.projectId,
        fileName = request.fileName,
        mimeType = request.mimeType,
        sizeBytes = request.sizeBytes,
        chunkSize = 4,
        totalChunks = 3,
        receivedChunks = receivedChunks,
        status = uploadStatus,
        pageId = null,
        expiresAt = "2026-10-21T00:00:00Z",
    )

    override suspend fun getUpload(uploadId: String): UploadDto = error("not expected")

    override suspend fun putChunk(uploadId: String, chunkIndex: Int, sha256: String, bytes: ByteArray): ChunkReceiptDto {
        chunkFailure?.let { throw it }
        sentChunks += chunkIndex
        return ChunkReceiptDto(uploadId, chunkIndex, bytes.size.toLong(), sha256)
    }

    override suspend fun completeUpload(uploadId: String) = PageDto(
        id = "page-1",
        projectId = "server-project",
        pageNumber = 1,
        qualityWarning = null,
        qualityDetails = null,
        activeResultVersion = 1,
        reviewStatus = "pending",
        ocrStatus = "pending",
    )
}

private class FakeStore(
    var project: LocalUploadProject,
    var upload: QueuedUpload,
) : UploadQueueStore {
    private var cleared = false

    override suspend fun allProjectIds(ownerUserId: String): List<String> =
        if (!cleared && project.ownerUserId == ownerUserId) listOf(project.localProjectId) else emptyList()

    override suspend fun localPaths(ownerUserId: String): List<String> =
        if (!cleared && upload.ownerUserId == ownerUserId) listOf(upload.localPath) else emptyList()

    override suspend fun clearUser(ownerUserId: String) {
        if (project.ownerUserId == ownerUserId) cleared = true
    }
    override suspend fun enqueue(project: LocalUploadProject, upload: QueuedUpload) {
        this.project = project
        this.upload = upload
    }

    override suspend fun project(ownerUserId: String, localProjectId: String) =
        project.takeIf { !cleared && it.ownerUserId == ownerUserId && it.localProjectId == localProjectId }

    override suspend fun nextPending(ownerUserId: String, localProjectId: String) = upload.takeIf {
        !cleared && it.ownerUserId == ownerUserId && it.localProjectId == localProjectId &&
            it.status in setOf(
                UploadQueueStatus.QUEUED,
                UploadQueueStatus.RETRYING,
                UploadQueueStatus.WAITING_FOR_LOGIN,
                UploadQueueStatus.UPLOADING,
            )
    }

    override suspend fun pendingProjectIds(ownerUserId: String) =
        if (!cleared && project.ownerUserId == ownerUserId) listOf(project.localProjectId) else emptyList()

    override suspend fun setServerProjectId(ownerUserId: String, localProjectId: String, serverProjectId: String) {
        project = project.copy(serverProjectId = serverProjectId)
    }

    override suspend fun setUploadSession(
        ownerUserId: String,
        uploadId: String,
        serverUploadId: String,
        sha256: String,
        uploadedBytes: Long,
        status: UploadQueueStatus,
    ) {
        upload = upload.copy(
            serverUploadId = serverUploadId,
            sha256 = sha256,
            uploadedBytes = uploadedBytes,
            status = status,
            errorCode = null,
        )
    }

    override suspend fun rotateUploadSession(ownerUserId: String, uploadId: String, idempotencyKey: String) {
        upload = upload.copy(
            idempotencyKey = idempotencyKey,
            serverUploadId = null,
            sha256 = null,
            uploadedBytes = 0,
            status = UploadQueueStatus.QUEUED,
            errorCode = null,
        )
    }

    override suspend fun updateProgress(ownerUserId: String, uploadId: String, uploadedBytes: Long) {
        upload = upload.copy(uploadedBytes = uploadedBytes, status = UploadQueueStatus.UPLOADING)
    }

    override suspend fun markStatus(ownerUserId: String, uploadId: String, status: UploadQueueStatus, errorCode: String?) {
        upload = upload.copy(status = status, errorCode = errorCode)
    }

    override suspend fun markCompleted(ownerUserId: String, uploadId: String, pageId: String) {
        upload = upload.copy(status = UploadQueueStatus.COMPLETED, pageId = pageId, uploadedBytes = upload.sizeBytes, errorCode = null)
    }
}
