package com.smartscan.feature.workspace

import com.smartscan.core.model.AiCapabilities
import com.smartscan.core.model.AiEnhancement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkspaceStateTest {
    @Test
    fun `page can move only inside project bounds`() {
        assertEquals(listOf("b", "a", "c"), movePage(listOf("a", "b", "c"), 0, 1))
        assertEquals(listOf("a", "c", "b"), movePage(listOf("a", "b", "c"), 2, -1))
        assertNull(movePage(listOf("a", "b"), 0, -1))
        assertNull(movePage(listOf("a", "b"), 1, 1))
    }

    @Test
    fun `AI state uses current source version and polls only running tasks`() {
        val old = enhancement("old", "candidate_ready", 1)
        val current = enhancement("current", "processing", 2)
        val items = listOf(old, current)

        assertEquals(current, latestAiEnhancement(items, 2, "recommended"))
        assertEquals(true, shouldPollAiEnhancements(items))
        assertEquals(false, canDecideAiEnhancement(current, 2))
        assertEquals(true, canDecideAiEnhancement(current.copy(status = "candidate_ready"), 2))
        assertEquals(false, canDecideAiEnhancement(old, 2))
    }

    @Test
    fun `complex OCR requires both public kind and task capability`() {
        val capabilities = AiCapabilities(
            available = true,
            businessOrchestrationReady = true,
            executionMode = "mock",
            consentVersion = "v1",
            transmissionNoticeCode = "notice",
            enhancementKinds = setOf("recommended", "complex_ocr"),
            taskTypes = setOf("classify_page"),
        )

        assertEquals(true, supportsAiEnhancement(capabilities, "recommended"))
        assertEquals(false, supportsAiEnhancement(capabilities, "complex_ocr"))
        assertEquals(true, supportsAiEnhancement(capabilities.copy(taskTypes = setOf("ocr_formula")), "complex_ocr"))
        assertEquals(92, aiConfidencePercent(0.919))
    }
}

private fun enhancement(id: String, status: String, version: Int) = AiEnhancement(
    id = id,
    projectId = "project-1",
    pageId = "page-1",
    processingJobId = null,
    enhancementKind = "recommended",
    requestedTasks = listOf("classify_page"),
    sourceResultVersion = version,
    status = status,
    candidates = emptyList(),
    confidence = null,
    errorCode = null,
    createdAt = "2026-10-22T00:00:00Z",
    updatedAt = "2026-10-22T00:00:00Z",
)
