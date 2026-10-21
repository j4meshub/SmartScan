package com.smartscan.data.repository

import com.smartscan.core.network.ChunkReceiptDto
import com.smartscan.core.network.CreateProjectRequestDto
import com.smartscan.core.network.CreateUploadRequestDto
import com.smartscan.core.network.PageDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ScanApi
import com.smartscan.core.network.UploadDto
import java.io.IOException
import kotlinx.coroutines.test.runTest
import okhttp3.RequestBody
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ProjectRepositoryTest {
    @Test
    fun `repository maps API DTO to domain model`() = runTest {
        val repository = DefaultProjectRepository(FakeApi())
        val result = assertIs<ApiResult.Success<*>>(repository.listProjects())
        val projects = result.value as List<*>
        assertEquals("资料", (projects.single() as com.smartscan.core.model.ScanProject).title)
    }

    @Test
    fun `network failure is retryable without exposing exception text`() = runTest {
        val repository = DefaultProjectRepository(FakeApi(error = IOException("secret-host")))
        val failure = assertIs<ApiResult.Failure>(repository.listProjects())
        assertEquals(FailureKind.NETWORK, failure.kind)
        assertEquals(true, failure.retryable)
    }

    @Test
    fun `network failure uses only the current user cached projects`() = runTest {
        val cache = ProjectCacheFake(
            mapOf("user-a" to listOf(com.smartscan.core.model.ScanProject("p1", "离线资料", null, "document", "ltr", "created", "updated"))),
        )
        val repository = DefaultProjectRepository(
            api = FakeApi(error = IOException("offline")),
            cache = cache,
            currentUserId = { "user-a" },
        )

        val result = assertIs<ApiResult.Success<*>>(repository.listProjects())
        val projects = result.value as List<*>
        assertEquals("离线资料", (projects.single() as com.smartscan.core.model.ScanProject).title)
        assertEquals(listOf("user-a"), cache.readUsers)
    }
}

private class ProjectCacheFake(
    private val projects: Map<String, List<com.smartscan.core.model.ScanProject>>,
) : UserScopedCache {
    val readUsers = mutableListOf<String>()
    override suspend fun replaceProjects(userId: String, projects: List<com.smartscan.core.model.ScanProject>) = Unit
    override suspend fun listProjects(userId: String): List<com.smartscan.core.model.ScanProject> {
        readUsers += userId
        return projects[userId].orEmpty()
    }
    override suspend fun clearUser(userId: String) = Unit
}

private class FakeApi(private val error: IOException? = null) : ScanApi {
    override suspend fun createProject(request: CreateProjectRequestDto): ProjectDto = kotlin.error("not expected")

    override suspend fun listProjects(): List<ProjectDto> {
        error?.let { throw it }
        return listOf(ProjectDto("p1", "u1", "资料", null, null, "document", "ltr", "created", "updated"))
    }

    override suspend fun listPages(projectId: String) = emptyList<com.smartscan.core.network.PageDto>()
    override suspend fun listJobs() = emptyList<com.smartscan.core.network.JobDto>()
    override suspend fun listExports(projectId: String) = emptyList<com.smartscan.core.network.ExportDto>()
    override suspend fun createUpload(request: CreateUploadRequestDto): UploadDto = kotlin.error("not expected")
    override suspend fun getUpload(uploadId: String): UploadDto = kotlin.error("not expected")
    override suspend fun putUploadChunk(
        uploadId: String,
        chunkIndex: Int,
        chunkSha256: String,
        body: RequestBody,
    ): ChunkReceiptDto = kotlin.error("not expected")
    override suspend fun completeUpload(uploadId: String): PageDto = kotlin.error("not expected")
}
