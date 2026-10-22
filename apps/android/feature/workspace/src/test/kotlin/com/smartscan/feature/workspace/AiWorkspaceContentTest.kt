package com.smartscan.feature.workspace

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.smartscan.core.model.AiCandidate
import com.smartscan.core.model.AiCapabilities
import com.smartscan.core.model.AiEnhancement
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
        var projectEnabled by mutableStateOf(false)
        compose.setContent {
            MaterialTheme {
                AiWorkspaceContent(
                    projectAiEnabled = projectEnabled,
                    activeResultVersion = 1,
                    capabilities = capabilities(),
                    enhancements = emptyList(),
                    enhancementKind = "recommended",
                    loading = false,
                    actionBusy = false,
                    parentBusy = false,
                    failed = false,
                    onToggleProjectAi = { projectEnabled = true },
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
        compose.onNodeWithText("Disable AI for this project").assertIsDisplayed()
        compose.onNodeWithText("Analyze this page").assertIsEnabled()
        compose.onAllNodesWithText("provider", substring = true, ignoreCase = true).assertCountEquals(0)
    }

    @Test
    fun `current candidate exposes user decision actions`() {
        var status by mutableStateOf("candidate_ready")
        val candidate = enhancement(status = status, sourceVersion = 2)
        compose.setContent {
            MaterialTheme {
                AiWorkspaceContent(
                    projectAiEnabled = true,
                    activeResultVersion = 2,
                    capabilities = capabilities(),
                    enhancements = listOf(candidate.copy(status = status)),
                    enhancementKind = "recommended",
                    loading = false,
                    actionBusy = false,
                    parentBusy = false,
                    failed = false,
                    onToggleProjectAi = {},
                    onEnhancementKindChanged = {},
                    onRequest = {},
                    onRefresh = {},
                    onDecide = { _, accepted -> status = if (accepted) "accepted" else "rejected" },
                    onPreviewVersion = {},
                )
            }
        }

        compose.onNodeWithText("Candidate ready").assertIsDisplayed()
        compose.onNodeWithText("Title suggestion").assertIsDisplayed()
        compose.onNodeWithText("Accept candidate").performClick()
        compose.onNodeWithText("Candidate accepted").assertIsDisplayed()
    }

    @Test
    fun `accepted history exposes read only baseline preview`() {
        var previewVersion by mutableStateOf<Int?>(null)
        val candidate = enhancement(status = "accepted", sourceVersion = 2)
        compose.setContent {
            MaterialTheme {
                Column {
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
                    Text("preview:${previewVersion ?: 0}")
                }
            }
        }
        compose.onNodeWithText("View baseline version").performClick()
        compose.onNodeWithText("preview:2").assertIsDisplayed()
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
