package com.smartscan.feature.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.smartscan.core.auth.SessionStore
import com.smartscan.core.upload.LocalUploadProject
import com.smartscan.core.upload.QueuedUpload
import com.smartscan.core.upload.UploadQueueStatus
import com.smartscan.core.upload.UploadQueueStore
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit

class UploadQueueCoordinator(
    context: Context,
    private val store: UploadQueueStore,
    private val sessions: SessionStore,
    private val workManager: WorkManager = WorkManager.getInstance(context.applicationContext),
) {
    private val captureRoot = File(context.filesDir, "captures/originals").canonicalFile

    suspend fun enqueue(
        localProjectId: String,
        title: String,
        mode: String,
        originalPath: String,
    ): Boolean {
        val ownerUserId = sessions.current()?.userId ?: return false
        val source = runCatching { File(originalPath).canonicalFile }.getOrNull() ?: return false
        if (!source.isFile || source.length() <= 15 || !source.toPath().startsWith(captureRoot.toPath())) return false
        val now = System.currentTimeMillis()
        val uploadId = UUID.randomUUID().toString()
        store.enqueue(
            LocalUploadProject(ownerUserId, localProjectId, title, mode, serverProjectId = null),
            QueuedUpload(
                ownerUserId = ownerUserId,
                id = uploadId,
                localProjectId = localProjectId,
                localPath = source.absolutePath,
                fileName = source.name,
                mimeType = "image/jpeg",
                sizeBytes = source.length(),
                sha256 = null,
                idempotencyKey = UUID.randomUUID().toString().replace("-", ""),
                serverUploadId = null,
                uploadedBytes = 0,
                status = UploadQueueStatus.QUEUED,
                pageId = null,
                errorCode = null,
                createdAtEpochMs = now,
            ),
        )
        schedule(ownerUserId, localProjectId)
        return true
    }

    suspend fun resumeCurrentUser() {
        val userId = sessions.current()?.userId ?: return
        store.pendingProjectIds(userId).forEach { schedule(userId, it) }
    }

    private fun schedule(ownerUserId: String, localProjectId: String) {
        val input = Data.Builder()
            .putString(UploadWorker.OWNER_USER_ID, ownerUserId)
            .putString(UploadWorker.LOCAL_PROJECT_ID, localProjectId)
            .build()
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setInputData(input)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
            .addTag("smartscan-upload")
            .build()
        workManager.enqueueUniqueWork(
            "smartscan-upload-$ownerUserId-$localProjectId",
            ExistingWorkPolicy.APPEND_OR_REPLACE,
            request,
        )
    }
}

interface UploadWorkerDependencies {
    val uploadSessionStore: SessionStore
    val uploadProcessor: UploadProcessor
    suspend fun refreshUploadSession(ownerUserId: String): Boolean
}

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val ownerUserId = inputData.getString(OWNER_USER_ID) ?: return Result.failure()
        val localProjectId = inputData.getString(LOCAL_PROJECT_ID) ?: return Result.failure()
        val dependencies = applicationContext as? UploadWorkerDependencies ?: return Result.failure()
        if (dependencies.uploadSessionStore.current()?.userId != ownerUserId) {
            dependencies.uploadProcessor.pauseForLogin(ownerUserId, localProjectId)
            return Result.success()
        }
        return when (dependencies.uploadProcessor.processProject(ownerUserId, localProjectId)) {
            UploadProcessResult.Success -> Result.success()
            UploadProcessResult.Retry -> Result.retry()
            UploadProcessResult.WaitingForLogin -> {
                if (dependencies.refreshUploadSession(ownerUserId)) {
                    Result.retry()
                } else {
                    dependencies.uploadProcessor.pauseForLogin(ownerUserId, localProjectId)
                    Result.success()
                }
            }
            UploadProcessResult.Failed -> Result.failure()
        }
    }

    companion object {
        const val OWNER_USER_ID = "owner_user_id"
        const val LOCAL_PROJECT_ID = "local_project_id"
    }
}
