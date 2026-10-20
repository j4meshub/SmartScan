package com.smartscan.data.repository

import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.SmartScanApi
import java.io.IOException
import kotlinx.coroutines.test.runTest
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
}

private class FakeApi(private val error: IOException? = null) : SmartScanApi {
    override suspend fun listProjects(): List<ProjectDto> {
        error?.let { throw it }
        return listOf(ProjectDto("p1", "u1", "资料", null, null, "document", "ltr", "created", "updated"))
    }

    override suspend fun listPages(projectId: String) = emptyList<com.smartscan.core.network.PageDto>()
    override suspend fun listJobs() = emptyList<com.smartscan.core.network.JobDto>()
    override suspend fun listExports(projectId: String) = emptyList<com.smartscan.core.network.ExportDto>()
}
