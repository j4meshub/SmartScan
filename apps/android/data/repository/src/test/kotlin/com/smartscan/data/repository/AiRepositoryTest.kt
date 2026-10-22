package com.smartscan.data.repository

import com.smartscan.core.network.AiApi
import com.smartscan.core.network.AiCapabilitiesDto
import com.smartscan.core.network.AiEnhancementDto
import com.smartscan.core.network.AiEnhancementRequestDto
import com.smartscan.core.network.ProjectAiSettingsRequestDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ScanApi
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class AiRepositoryTest {
    @Test
    fun `capabilities and consent map without provider configuration`() = runTest {
        val ai = FakeAiApi()
        val repository = DefaultProjectRepository(EmptyScanApi(), aiApi = ai)

        val capabilities = (repository.getAiCapabilities() as ApiResult.Success).value
        val project = (repository.updateProjectAiSettings("project-1", true, capabilities.consentVersion) as ApiResult.Success).value

        assertTrue(capabilities.available)
        assertEquals("mock", capabilities.executionMode)
        assertTrue(project.aiEnabled)
        assertEquals("2026-10-22.1", ai.lastSettings?.consentVersion)
        assertFalse(project.toString().contains("provider", ignoreCase = true))
    }

    @Test
    fun `structured candidate is bounded and normalized for Android UI`() = runTest {
        val repository = DefaultProjectRepository(EmptyScanApi(), aiApi = FakeAiApi())

        val result = repository.listAiEnhancements("page-1") as ApiResult.Success
        val candidates = result.value.single().candidates

        assertEquals(
            listOf("classification", "orientation", "title", "page_number", "formula", "table", "layout"),
            candidates.map { it.kind },
        )
        assertEquals("第二候选", candidates.first { it.kind == "title" }.value)
        assertEquals("甲 | 乙 / 丙", candidates.first { it.kind == "table" }.value)
        assertEquals(512, candidates.first { it.kind == "layout" }.value.length)
    }

    @Test
    fun `request uses stable explicit idempotency key and supported kinds only`() = runTest {
        val ai = FakeAiApi()
        val repository = DefaultProjectRepository(EmptyScanApi(), aiApi = ai)
        val key = "android-ai.page-1.v4.00000000-0000-4000-8000-000000000001"

        val result = repository.requestAiEnhancement("page-1", "complex_ocr", 4, key)

        assertTrue(result is ApiResult.Success)
        assertEquals(key, ai.lastIdempotencyKey)
        assertTrue(key.startsWith("android-ai.page-1.v4."))
        val unsupported = repository.requestAiEnhancement("page-1", "exam_review", 4, key)
        assertEquals(FailureKind.INVALID_RESPONSE, (unsupported as ApiResult.Failure).kind)
    }
}

private class FakeAiApi : AiApi {
    var lastSettings: ProjectAiSettingsRequestDto? = null
    var lastIdempotencyKey: String? = null

    override suspend fun getAiCapabilities() = AiCapabilitiesDto(
        available = true,
        businessOrchestrationReady = true,
        executionMode = "mock",
        consentVersion = "2026-10-22.1",
        transmissionNoticeCode = "ai_data_transfer_v1",
        enhancementKinds = listOf("recommended", "complex_ocr"),
        taskTypes = listOf("classify_page", "detect_orientation", "extract_title", "extract_page_number", "ocr_formula"),
    )

    override suspend fun updateProjectAiSettings(
        projectId: String,
        request: ProjectAiSettingsRequestDto,
    ): ProjectDto {
        lastSettings = request
        return project(request.enabled, request.consentVersion)
    }

    override suspend fun createAiEnhancement(
        pageId: String,
        idempotencyKey: String,
        request: AiEnhancementRequestDto,
    ): AiEnhancementDto {
        lastIdempotencyKey = idempotencyKey
        return enhancement(request.enhancementKind, request.sourceResultVersion)
    }

    override suspend fun listAiEnhancements(pageId: String) = listOf(enhancement("complex_ocr", 4))
    override suspend fun acceptAiEnhancement(enhancementId: String) = enhancement("recommended", 4).copy(status = "accepted")
    override suspend fun rejectAiEnhancement(enhancementId: String) = enhancement("recommended", 4).copy(status = "rejected")
}

private class EmptyScanApi : ScanApi {
    override suspend fun createProject(request: com.smartscan.core.network.CreateProjectRequestDto): ProjectDto = error("not used")
    override suspend fun listProjects() = emptyList<ProjectDto>()
    override suspend fun listPages(projectId: String) = emptyList<com.smartscan.core.network.PageDto>()
    override suspend fun listJobs() = emptyList<com.smartscan.core.network.JobDto>()
    override suspend fun listExports(projectId: String) = emptyList<com.smartscan.core.network.ExportDto>()
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

private fun project(enabled: Boolean, consentVersion: String?) = ProjectDto(
    id = "project-1",
    ownerUserId = "user-1",
    title = "资料",
    suggestedName = null,
    suggestedNameSource = null,
    mode = "document",
    readingOrder = "ltr",
    aiEnabled = enabled,
    aiConsentVersion = consentVersion,
    createdAt = "2026-10-22T00:00:00Z",
    updatedAt = "2026-10-22T00:00:00Z",
)

private fun enhancement(kind: String, version: Int) = AiEnhancementDto(
    id = "enhancement-1",
    projectId = "project-1",
    pageId = "page-1",
    processingJobId = "job-1",
    enhancementKind = kind,
    requestedTasks = if (kind == "complex_ocr") listOf("ocr_formula") else listOf("classify_page"),
    sourceResultVersion = version,
    status = "candidate_ready",
    candidateResult = candidateResult(),
    confidence = 0.91,
    createdAt = "2026-10-22T00:00:00Z",
    updatedAt = "2026-10-22T00:00:01Z",
)

private fun candidateResult(): JsonElement = Json.parseToJsonElement(
    """
    {
      "tasks": {
        "classify_page": {"label": "document", "confidence": 0.91},
        "detect_orientation": {"rotation_degrees": 90, "confidence": 0.82},
        "extract_title": {"candidates": [
          {"text": "第一候选", "confidence": 0.51},
          {"text": "第二候选", "confidence": 0.95}
        ]},
        "extract_page_number": {"status": "detected", "raw_label": "12", "confidence": 0.88},
        "ocr_formula": {"blocks": [
          {"block_type": "formula", "latex_candidate": "x^2+y^2", "confidence": 0.93},
          {"block_type": "table", "confidence": 0.84, "cells": [
            {"row": 0, "column": 1, "text_candidate": "乙"},
            {"row": 0, "column": 0, "text_candidate": "甲"},
            {"row": 1, "column": 0, "text_candidate": "丙"}
          ]},
          {"block_type": "layout", "text_candidate": "${"版".repeat(600)}", "confidence": 0.75}
        ]}
      }
    }
    """.trimIndent(),
)
