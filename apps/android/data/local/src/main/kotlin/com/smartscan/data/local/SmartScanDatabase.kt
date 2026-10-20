package com.smartscan.data.local

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.ColumnInfo
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.smartscan.core.model.ScanProject
import com.smartscan.core.upload.LocalUploadProject
import com.smartscan.core.upload.QueuedUpload
import com.smartscan.core.upload.UploadQueueStatus
import com.smartscan.core.upload.UploadQueueStore
import com.smartscan.data.repository.UserScopedCache

@Entity(tableName = "cached_projects", primaryKeys = ["owner_user_id", "id"])
data class CachedProjectEntity(
    @ColumnInfo(name = "owner_user_id")
    val ownerUserId: String,
    val id: String,
    val title: String,
    val suggestedName: String?,
    val mode: String,
    val readingOrder: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(tableName = "local_upload_projects", primaryKeys = ["owner_user_id", "local_project_id"])
data class LocalUploadProjectEntity(
    @ColumnInfo(name = "owner_user_id") val ownerUserId: String,
    @ColumnInfo(name = "local_project_id") val localProjectId: String,
    val title: String,
    val mode: String,
    @ColumnInfo(name = "server_project_id") val serverProjectId: String?,
)

@Entity(tableName = "queued_uploads", primaryKeys = ["owner_user_id", "id"])
data class QueuedUploadEntity(
    @ColumnInfo(name = "owner_user_id") val ownerUserId: String,
    val id: String,
    @ColumnInfo(name = "local_project_id") val localProjectId: String,
    @ColumnInfo(name = "local_path") val localPath: String,
    @ColumnInfo(name = "file_name") val fileName: String,
    @ColumnInfo(name = "mime_type") val mimeType: String,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long,
    val sha256: String?,
    @ColumnInfo(name = "idempotency_key") val idempotencyKey: String,
    @ColumnInfo(name = "server_upload_id") val serverUploadId: String?,
    @ColumnInfo(name = "uploaded_bytes") val uploadedBytes: Long,
    val status: String,
    @ColumnInfo(name = "page_id") val pageId: String?,
    @ColumnInfo(name = "error_code") val errorCode: String?,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtEpochMs: Long,
)

@Dao
interface CachedProjectDao {
    @Query("SELECT * FROM cached_projects WHERE owner_user_id = :userId ORDER BY updatedAt DESC")
    suspend fun listForUser(userId: String): List<CachedProjectEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(projects: List<CachedProjectEntity>)

    @Query("DELETE FROM cached_projects WHERE owner_user_id = :userId")
    suspend fun clearUser(userId: String)

    @Transaction
    suspend fun replaceForUser(userId: String, projects: List<CachedProjectEntity>) {
        require(projects.all { it.ownerUserId == userId }) { "cache_owner_mismatch" }
        clearUser(userId)
        insertAll(projects)
    }
}

@Dao
interface UploadQueueDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertProject(project: LocalUploadProjectEntity): Long

    @Query("SELECT * FROM local_upload_projects WHERE owner_user_id = :userId AND local_project_id = :localProjectId")
    suspend fun project(userId: String, localProjectId: String): LocalUploadProjectEntity?

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertUpload(upload: QueuedUploadEntity)

    @Transaction
    suspend fun enqueue(projectEntity: LocalUploadProjectEntity, upload: QueuedUploadEntity) {
        val existing = project(projectEntity.ownerUserId, projectEntity.localProjectId)
        if (existing != null) {
            require(existing.title == projectEntity.title && existing.mode == projectEntity.mode) { "queue_project_conflict" }
        } else {
            insertProject(projectEntity)
        }
        insertUpload(upload)
    }

    @Query(
        "SELECT * FROM queued_uploads WHERE owner_user_id = :userId AND local_project_id = :localProjectId " +
            "AND status IN ('QUEUED', 'RETRYING', 'WAITING_FOR_LOGIN', 'UPLOADING') ORDER BY created_at_epoch_ms, id LIMIT 1",
    )
    suspend fun nextPending(userId: String, localProjectId: String): QueuedUploadEntity?

    @Query(
        "SELECT DISTINCT local_project_id FROM queued_uploads WHERE owner_user_id = :userId " +
            "AND status IN ('QUEUED', 'RETRYING', 'WAITING_FOR_LOGIN', 'UPLOADING') ORDER BY local_project_id",
    )
    suspend fun pendingProjectIds(userId: String): List<String>

    @Query(
        "UPDATE local_upload_projects SET server_project_id = :serverProjectId " +
            "WHERE owner_user_id = :userId AND local_project_id = :localProjectId",
    )
    suspend fun setServerProjectId(userId: String, localProjectId: String, serverProjectId: String): Int

    @Query(
        "UPDATE queued_uploads SET server_upload_id = :serverUploadId, sha256 = :sha256, " +
            "uploaded_bytes = :uploadedBytes, status = :status, error_code = NULL " +
            "WHERE owner_user_id = :userId AND id = :uploadId",
    )
    suspend fun setUploadSession(
        userId: String,
        uploadId: String,
        serverUploadId: String,
        sha256: String,
        uploadedBytes: Long,
        status: String,
    ): Int

    @Query(
        "UPDATE queued_uploads SET idempotency_key = :idempotencyKey, server_upload_id = NULL, sha256 = NULL, " +
            "uploaded_bytes = 0, status = 'QUEUED', error_code = NULL WHERE owner_user_id = :userId AND id = :uploadId",
    )
    suspend fun rotateUploadSession(userId: String, uploadId: String, idempotencyKey: String): Int

    @Query(
        "UPDATE queued_uploads SET uploaded_bytes = :uploadedBytes, status = 'UPLOADING', error_code = NULL " +
            "WHERE owner_user_id = :userId AND id = :uploadId",
    )
    suspend fun updateProgress(userId: String, uploadId: String, uploadedBytes: Long): Int

    @Query(
        "UPDATE queued_uploads SET status = :status, error_code = :errorCode " +
            "WHERE owner_user_id = :userId AND id = :uploadId",
    )
    suspend fun markStatus(userId: String, uploadId: String, status: String, errorCode: String?): Int

    @Query(
        "UPDATE queued_uploads SET status = 'COMPLETED', page_id = :pageId, error_code = NULL, uploaded_bytes = size_bytes " +
            "WHERE owner_user_id = :userId AND id = :uploadId",
    )
    suspend fun markCompleted(userId: String, uploadId: String, pageId: String): Int
}

@Database(
    entities = [CachedProjectEntity::class, LocalUploadProjectEntity::class, QueuedUploadEntity::class],
    version = 2,
    exportSchema = false,
)
abstract class SmartScanDatabase : RoomDatabase() {
    abstract fun cachedProjects(): CachedProjectDao
    abstract fun uploadQueue(): UploadQueueDao
}

data class LocalStores(
    val userCache: UserScopedCache,
    val uploadQueue: UploadQueueStore,
)

fun openLocalStores(context: Context): LocalStores {
    val database = Room.databaseBuilder(
        context.applicationContext,
        SmartScanDatabase::class.java,
        "smartscan-cache.db",
    ).addMigrations(MIGRATION_1_2).build()
    return LocalStores(
        userCache = RoomUserScopedCache(database.cachedProjects()),
        uploadQueue = RoomUploadQueueStore(database.uploadQueue()),
    )
}

class RoomUserScopedCache(private val dao: CachedProjectDao) : UserScopedCache {
    override suspend fun replaceProjects(userId: String, projects: List<ScanProject>) {
        require(userId.isNotBlank()) { "cache_user_required" }
        dao.replaceForUser(userId, projects.map { it.toEntity(userId) })
    }

    override suspend fun listProjects(userId: String): List<ScanProject> {
        require(userId.isNotBlank()) { "cache_user_required" }
        return dao.listForUser(userId).map(CachedProjectEntity::toModel)
    }

    override suspend fun clearUser(userId: String) {
        require(userId.isNotBlank()) { "cache_user_required" }
        dao.clearUser(userId)
    }
}

class RoomUploadQueueStore(private val dao: UploadQueueDao) : UploadQueueStore {
    override suspend fun enqueue(project: LocalUploadProject, upload: QueuedUpload) {
        require(project.ownerUserId == upload.ownerUserId) { "queue_owner_mismatch" }
        require(project.localProjectId == upload.localProjectId) { "queue_project_mismatch" }
        dao.enqueue(project.toEntity(), upload.toEntity())
    }

    override suspend fun project(ownerUserId: String, localProjectId: String): LocalUploadProject? =
        dao.project(ownerUserId.requiredUserId(), localProjectId).let { it?.toModel() }

    override suspend fun nextPending(ownerUserId: String, localProjectId: String): QueuedUpload? =
        dao.nextPending(ownerUserId.requiredUserId(), localProjectId).let { it?.toModel() }

    override suspend fun pendingProjectIds(ownerUserId: String): List<String> =
        dao.pendingProjectIds(ownerUserId.requiredUserId())

    override suspend fun setServerProjectId(ownerUserId: String, localProjectId: String, serverProjectId: String) {
        require(dao.setServerProjectId(ownerUserId.requiredUserId(), localProjectId, serverProjectId) == 1) { "queue_project_missing" }
    }

    override suspend fun setUploadSession(
        ownerUserId: String,
        uploadId: String,
        serverUploadId: String,
        sha256: String,
        uploadedBytes: Long,
        status: UploadQueueStatus,
    ) {
        require(dao.setUploadSession(ownerUserId.requiredUserId(), uploadId, serverUploadId, sha256, uploadedBytes, status.name) == 1) {
            "queue_upload_missing"
        }
    }

    override suspend fun rotateUploadSession(ownerUserId: String, uploadId: String, idempotencyKey: String) {
        require(dao.rotateUploadSession(ownerUserId.requiredUserId(), uploadId, idempotencyKey) == 1) { "queue_upload_missing" }
    }

    override suspend fun updateProgress(ownerUserId: String, uploadId: String, uploadedBytes: Long) {
        require(dao.updateProgress(ownerUserId.requiredUserId(), uploadId, uploadedBytes) == 1) { "queue_upload_missing" }
    }

    override suspend fun markStatus(ownerUserId: String, uploadId: String, status: UploadQueueStatus, errorCode: String?) {
        require(dao.markStatus(ownerUserId.requiredUserId(), uploadId, status.name, errorCode) == 1) { "queue_upload_missing" }
    }

    override suspend fun markCompleted(ownerUserId: String, uploadId: String, pageId: String) {
        require(dao.markCompleted(ownerUserId.requiredUserId(), uploadId, pageId) == 1) { "queue_upload_missing" }
    }
}

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS local_upload_projects (" +
                "owner_user_id TEXT NOT NULL, local_project_id TEXT NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL, " +
                "server_project_id TEXT, PRIMARY KEY(owner_user_id, local_project_id))",
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS queued_uploads (" +
                "owner_user_id TEXT NOT NULL, id TEXT NOT NULL, local_project_id TEXT NOT NULL, local_path TEXT NOT NULL, " +
                "file_name TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT, " +
                "idempotency_key TEXT NOT NULL, server_upload_id TEXT, uploaded_bytes INTEGER NOT NULL, status TEXT NOT NULL, " +
                "page_id TEXT, error_code TEXT, created_at_epoch_ms INTEGER NOT NULL, PRIMARY KEY(owner_user_id, id))",
        )
    }
}

private fun ScanProject.toEntity(ownerUserId: String) = CachedProjectEntity(
    ownerUserId = ownerUserId,
    id = id,
    title = title,
    suggestedName = suggestedName,
    mode = mode,
    readingOrder = readingOrder,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun CachedProjectEntity.toModel() = ScanProject(
    id = id,
    title = title,
    suggestedName = suggestedName,
    mode = mode,
    readingOrder = readingOrder,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun LocalUploadProject.toEntity() = LocalUploadProjectEntity(
    ownerUserId = ownerUserId,
    localProjectId = localProjectId,
    title = title,
    mode = mode,
    serverProjectId = serverProjectId,
)

private fun LocalUploadProjectEntity.toModel() = LocalUploadProject(
    ownerUserId = ownerUserId,
    localProjectId = localProjectId,
    title = title,
    mode = mode,
    serverProjectId = serverProjectId,
)

private fun QueuedUpload.toEntity() = QueuedUploadEntity(
    ownerUserId = ownerUserId,
    id = id,
    localProjectId = localProjectId,
    localPath = localPath,
    fileName = fileName,
    mimeType = mimeType,
    sizeBytes = sizeBytes,
    sha256 = sha256,
    idempotencyKey = idempotencyKey,
    serverUploadId = serverUploadId,
    uploadedBytes = uploadedBytes,
    status = status.name,
    pageId = pageId,
    errorCode = errorCode,
    createdAtEpochMs = createdAtEpochMs,
)

private fun QueuedUploadEntity.toModel() = QueuedUpload(
    ownerUserId = ownerUserId,
    id = id,
    localProjectId = localProjectId,
    localPath = localPath,
    fileName = fileName,
    mimeType = mimeType,
    sizeBytes = sizeBytes,
    sha256 = sha256,
    idempotencyKey = idempotencyKey,
    serverUploadId = serverUploadId,
    uploadedBytes = uploadedBytes,
    status = UploadQueueStatus.valueOf(status),
    pageId = pageId,
    errorCode = errorCode,
    createdAtEpochMs = createdAtEpochMs,
)

private fun String.requiredUserId(): String = apply { require(isNotBlank()) { "queue_user_required" } }
