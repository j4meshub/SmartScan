package com.smartscan.core.upload

enum class UploadQueueStatus {
    QUEUED,
    UPLOADING,
    WAITING_FOR_LOGIN,
    RETRYING,
    COMPLETED,
    FAILED,
}

data class LocalUploadProject(
    val ownerUserId: String,
    val localProjectId: String,
    val title: String,
    val mode: String,
    val serverProjectId: String?,
)

data class QueuedUpload(
    val ownerUserId: String,
    val id: String,
    val localProjectId: String,
    val localPath: String,
    val fileName: String,
    val mimeType: String,
    val sizeBytes: Long,
    val sha256: String?,
    val idempotencyKey: String,
    val serverUploadId: String?,
    val uploadedBytes: Long,
    val status: UploadQueueStatus,
    val pageId: String?,
    val errorCode: String?,
    val createdAtEpochMs: Long,
)

interface UploadQueueStore {
    suspend fun enqueue(project: LocalUploadProject, upload: QueuedUpload)
    suspend fun project(ownerUserId: String, localProjectId: String): LocalUploadProject?
    suspend fun nextPending(ownerUserId: String, localProjectId: String): QueuedUpload?
    suspend fun pendingProjectIds(ownerUserId: String): List<String>
    suspend fun setServerProjectId(ownerUserId: String, localProjectId: String, serverProjectId: String)
    suspend fun setUploadSession(
        ownerUserId: String,
        uploadId: String,
        serverUploadId: String,
        sha256: String,
        uploadedBytes: Long,
        status: UploadQueueStatus,
    )
    suspend fun rotateUploadSession(ownerUserId: String, uploadId: String, idempotencyKey: String)
    suspend fun updateProgress(ownerUserId: String, uploadId: String, uploadedBytes: Long)
    suspend fun markStatus(ownerUserId: String, uploadId: String, status: UploadQueueStatus, errorCode: String?)
    suspend fun markCompleted(ownerUserId: String, uploadId: String, pageId: String)
}
