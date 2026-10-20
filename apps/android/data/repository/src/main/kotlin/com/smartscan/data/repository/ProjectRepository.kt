package com.smartscan.data.repository

import com.smartscan.core.model.ScanProject
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ScanApi
import java.io.IOException
import kotlinx.serialization.SerializationException
import retrofit2.HttpException

interface ProjectRepository {
    suspend fun listProjects(): ApiResult<List<ScanProject>>
}

class DefaultProjectRepository(
    private val api: ScanApi,
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
