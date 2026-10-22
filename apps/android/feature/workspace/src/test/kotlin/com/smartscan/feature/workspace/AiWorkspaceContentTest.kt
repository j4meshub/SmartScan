package com.smartscan.feature.workspace

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.smartscan.core.model.AiCandidate
import com.smartscan.core.model.AiCapabilities
import com.smartscan.core.model.AiEnhancement
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AiWorkspaceContentTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun `disabled project shows notice and mock identity before explicit consent`() {
        var toggled = false
        compose.setContent {
            MaterialTheme {
                AiWorkspaceContent(
                    projectAiEnabled = false,
                    activeResultVersion = 1,
                    capabilities = capabilities(),
                    enhancements = emptyList(),
                    enhancementKind = "recommended",
                    loading = false,
                    actionBusy = false,
                    parentBusy = false,
                    failed = false,
                    onToggleProjectAi = { toggled = true },
                    onEnhancementKindChanged = {},
                    onRequest = {},
                    onRefresh = {},
                    onDecide = { _, _ -> },
                    onPreviewVersion = {},
                )
            }
        }

        compose.onNodeWithText("Simulated AI").assertIsDisplayed()
        compose.onNodeWithText("Agree and enable AI for this project")
            .assertIsDisplayed()
            .assertHasClickAction()
            .performClick()
        compose.onNodeWithText("Analyze this page").assertIsNotEnabled()
        compose.onAllNodesWithText("provider", substring = true, ignoreCase = true).assertCountEquals(0)
        assertTrue(toggled)
    }

    @Test
    fun `current candidate exposes user decision actions`() {
        var decision: Boolean? = null
        val candidate = enhancement(status = "candidate_ready", sourceVersion = 2)
        compose.setContent {
            MaterialTheme {
                AiWorkspaceContent(
                    projectAiEnabled = true,
                    activeResultVersion = 2,
                    capabilities = capabilities(),
                    enhancements = listOf(candidate),
                    enhancementKind = "recommended",
                    loading = false,
                    actionBusy = false,
                    parentBusy = false,
                    failed = false,
                    onToggleProjectAi = {},
                    onEnhancementKindChanged = {},
                    onRequest = {},
                    onRefresh = {},
                    onDecide = { _, accepted -> decision = accepted },
                    onPreviewVersion = {},
                )
            }
        }

        compose.onNodeWithText("Candidate ready").assertIsDisplayed()
        compose.onNodeWithText("Title suggestion").assertIsDisplayed()
        compose.onNodeWithText("Accept candidate").performClick()
        compose.runOnIdle { assertEquals(true, decision) }
    }

    @Test
    fun `accepted history exposes read only baseline preview`() {
        var previewVersion: Int? = null
        val candidate = enhancement(status = "accepted", sourceVersion = 2)
        compose.setContent {
            MaterialTheme {
                AiWorkspaceContent(
                    projectAiEnabled = true,
                    activeResultVersion = 3,
                    capabilities = capabilities(),
                    enhancements = listOf(candidate),
                    enhancementKind = "recommended",
                    loading = false,
                    actionBusy = false,
                    parentBusy = false,
                    failed = false,
                    onToggleProjectAi = {},
                    onEnhancementKindChanged = {},
                    onRequest = {},
                    onRefresh = {},
                    onDecide = { _, _ -> },
                    onPreviewVersion = { previewVersion = it },
                )
            }
        }
        compose.onNodeWithText("View baseline version").performClick()
        compose.runOnIdle { assertEquals(2, previewVersion) }
    }
}

private fun capabilities() = AiCapabilities(
    available = true,
    businessOrchestrationReady = true,
    executionMode = "mock",
    consentVersion = "2026-10-22.1",
    transmissionNoticeCode = "ai_data_transfer_v1",
    enhancementKinds = setOf("recommended", "complex_ocr"),
    taskTypes = setOf("classify_page", "ocr_formula"),
)

private fun enhancement(status: String, sourceVersion: Int) = AiEnhancement(
    id = "enhancement-1",
    projectId = "project-1",
    pageId = "page-1",
    processingJobId = null,
    enhancementKind = "recommended",
    requestedTasks = listOf("extract_title"),
    sourceResultVersion = sourceVersion,
    status = status,
    candidates = listOf(AiCandidate("title", "Candidate title", 0.91)),
    confidence = 0.91,
    errorCode = null,
    createdAt = "2026-10-22T00:00:00Z",
    updatedAt = "2026-10-22T00:00:01Z",
)
