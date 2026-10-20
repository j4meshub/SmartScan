package com.smartscan.feature.sync

import com.smartscan.core.network.ChunkReceiptDto
import com.smartscan.core.network.CreateProjectRequestDto
import com.smartscan.core.network.CreateUploadRequestDto
import com.smartscan.core.network.PageDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.SmartScanApi
import com.smartscan.core.network.UploadDto
import com.smartscan.core.upload.QueuedUpload
import com.smartscan.core.upload.UploadQueueStatus
import com.smartscan.core.upload.UploadQueueStore
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

interface UploadRemote {
    suspend fun createProject(request: CreateProjectRequestDto): ProjectDto
    suspend fun createUpload(request: CreateUploadRequestDto): UploadDto
    suspend fun getUpload(uploadId: String): UploadDto
    suspend fun putChunk(uploadId: String, chunkIndex: Int, sha256: String, bytes: ByteArray): ChunkReceiptDto
    suspend fun completeUpload(uploadId: String): PageDto
}

class RetrofitUploadRemote(private val api: SmartScanApi) : UploadRemote {
    override suspend fun createProject(request: CreateProjectRequestDto) = api.createProject(request)
    override suspend fun createUpload(request: CreateUploadRequestDto) = api.createUpload(request)
    override suspend fun getUpload(uploadId: String) = api.getUpload(uploadId)
    override suspend fun putChunk(uploadId: String, chunkIndex: Int, sha256: String, bytes: ByteArray) =
        api.putUploadChunk(uploadId, chunkIndex, sha256, bytes.toRequestBody("application/octet-stream".toMediaType()))
    override suspend fun completeUpload(uploadId: String) = api.completeUpload(uploadId)
}

sealed interface UploadProcessResult {
    data object Success : UploadProcessResult
    data object Retry : UploadProcessResult
    data object WaitingForLogin : UploadProcessResult
    data object Failed : UploadProcessResult
}

class UploadProcessor(
    private val remote: UploadRemote,
    private val store: UploadQueueStore,
) {
    suspend fun processProject(ownerUserId: String, localProjectId: String): UploadProcessResult {
        require(ownerUserId.isNotBlank()) { "upload_owner_required" }
        val localProject = store.project(ownerUserId, localProjectId) ?: return UploadProcessResult.Failed
        val serverProjectId = localProject.serverProjectId ?: try {
            remote.createProject(CreateProjectRequestDto(localProject.title, localProject.mode)).id.also {
                store.setServerProjectId(ownerUserId, localProjectId, it)
            }
        } catch (failure: Exception) {
            return classifyProjectFailure(failure)
        }

        while (true) {
            val upload = store.nextPending(ownerUserId, localProjectId) ?: return UploadProcessResult.Success
            val result = processUpload(serverProjectId, upload)
            if (result != UploadProcessResult.Success) return result
        }
    }

    suspend fun pauseForLogin(ownerUserId: String, localProjectId: String) {
        store.nextPending(ownerUserId, localProjectId)?.let {
            store.markStatus(ownerUserId, it.id, UploadQueueStatus.WAITING_FOR_LOGIN, "login_required")
        }
    }

    private suspend fun processUpload(serverProjectId: String, upload: QueuedUpload): UploadProcessResult {
        val source = File(upload.localPath)
        if (!source.isFile || source.length() != upload.sizeBytes) {
            store.markStatus(upload.ownerUserId, upload.id, UploadQueueStatus.FAILED, "local_file_missing")
            return UploadProcessResult.Failed
        }
        store.markStatus(upload.ownerUserId, upload.id, UploadQueueStatus.UPLOADING, null)

        return try {
            val fileHash = upload.sha256 ?: sha256(source)
            val remoteUpload = if (upload.serverUploadId != null) {
                remote.getUpload(upload.serverUploadId)
            } else {
                remote.createUpload(
                    CreateUploadRequestDto(
                        projectId = serverProjectId,
                        fileName = upload.fileName,
                        mimeType = upload.mimeType,
                        sizeBytes = upload.sizeBytes,
                        sha256 = fileHash,
                        idempotencyKey = upload.idempotencyKey,
                    ),
                )
            }
            if (remoteUpload.status == "expired") {
                store.rotateUploadSession(upload.ownerUserId, upload.id, newIdempotencyKey())
                return UploadProcessResult.Retry
            }
            if (remoteUpload.status == "completed" && remoteUpload.pageId != null) {
                store.markCompleted(upload.ownerUserId, upload.id, requireNotNull(remoteUpload.pageId))
                return UploadProcessResult.Success
            }
            validateRemoteUpload(remoteUpload, upload)
            val received = remoteUpload.receivedChunks.toSet()
            var uploadedBytes = received.sumOf { index -> chunkLength(index, remoteUpload.chunkSize, upload.sizeBytes) }
            store.setUploadSession(
                upload.ownerUserId,
                upload.id,
                remoteUpload.id,
                fileHash,
                uploadedBytes,
                UploadQueueStatus.UPLOADING,
            )
            RandomAccessFile(source, "r").use { file ->
                for (index in 0 until remoteUpload.totalChunks) {
                    if (index in received) continue
                    val bytes = readChunk(file, index, remoteUpload.chunkSize, upload.sizeBytes)
                    val chunkHash = sha256(bytes)
                    val receipt = remote.putChunk(remoteUpload.id, index, chunkHash, bytes)
                    require(
                        receipt.uploadId == remoteUpload.id && receipt.chunkIndex == index &&
                            receipt.sizeBytes == bytes.size.toLong() && receipt.sha256 == chunkHash,
                    ) { "invalid_chunk_receipt" }
                    uploadedBytes += bytes.size
                    store.updateProgress(upload.ownerUserId, upload.id, uploadedBytes)
                }
            }
            val page = remote.completeUpload(remoteUpload.id)
            store.markCompleted(upload.ownerUserId, upload.id, page.id)
            UploadProcessResult.Success
        } catch (failure: Exception) {
            classifyUploadFailure(upload, failure)
        }
    }

    private suspend fun classifyProjectFailure(failure: Exception): UploadProcessResult = when {
        failure is HttpException && failure.code() == 401 -> UploadProcessResult.WaitingForLogin
        failure is IOException || failure is HttpException && (failure.code() == 408 || failure.code() == 429 || failure.code() >= 500) ->
            UploadProcessResult.Retry
        else -> UploadProcessResult.Failed
    }

    private suspend fun classifyUploadFailure(upload: QueuedUpload, failure: Exception): UploadProcessResult {
        val result = when {
            failure is HttpException && failure.code() == 401 -> UploadProcessResult.WaitingForLogin
            failure is HttpException && failure.code() == 410 -> {
                store.rotateUploadSession(upload.ownerUserId, upload.id, newIdempotencyKey())
                return UploadProcessResult.Retry
            }
            failure is IOException || failure is HttpException && (failure.code() == 408 || failure.code() == 429 || failure.code() >= 500) ->
                UploadProcessResult.Retry
            else -> UploadProcessResult.Failed
        }
        val status = when (result) {
            UploadProcessResult.WaitingForLogin -> UploadQueueStatus.WAITING_FOR_LOGIN
            UploadProcessResult.Retry -> UploadQueueStatus.RETRYING
            else -> UploadQueueStatus.FAILED
        }
        val errorCode = when (result) {
            UploadProcessResult.WaitingForLogin -> "login_required"
            UploadProcessResult.Retry -> "transient_failure"
            else -> "upload_failed"
        }
        store.markStatus(upload.ownerUserId, upload.id, status, errorCode)
        return result
    }

    private fun validateRemoteUpload(remote: UploadDto, local: QueuedUpload) {
        require(remote.sizeBytes == local.sizeBytes) { "upload_size_mismatch" }
        require(remote.chunkSize > 0 && remote.totalChunks > 0) { "invalid_chunk_plan" }
        val expectedChunks = (local.sizeBytes + remote.chunkSize - 1) / remote.chunkSize
        require(remote.totalChunks.toLong() == expectedChunks) { "invalid_chunk_plan" }
        require(remote.receivedChunks.all { it in 0 until remote.totalChunks }) { "invalid_received_chunk" }
    }
}

private fun readChunk(file: RandomAccessFile, index: Int, chunkSize: Long, totalSize: Long): ByteArray {
    val offset = index * chunkSize
    val length = chunkLength(index, chunkSize, totalSize)
    require(length in 1..Int.MAX_VALUE.toLong()) { "invalid_chunk_size" }
    val bytes = ByteArray(length.toInt())
    file.seek(offset)
    file.readFully(bytes)
    return bytes
}

private fun chunkLength(index: Int, chunkSize: Long, totalSize: Long): Long =
    minOf(chunkSize, totalSize - index * chunkSize).also { require(it > 0) { "invalid_chunk_index" } }

private fun sha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
    }
    return digest.digest().toHex()
}

private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).toHex()
private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xFF) }
private fun newIdempotencyKey(): String = UUID.randomUUID().toString().replace("-", "")
