package com.smartscan.data.local

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.ColumnInfo
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Transaction
import com.smartscan.core.model.ScanProject
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

@Database(entities = [CachedProjectEntity::class], version = 1, exportSchema = false)
abstract class SmartScanDatabase : RoomDatabase() {
    abstract fun cachedProjects(): CachedProjectDao
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
