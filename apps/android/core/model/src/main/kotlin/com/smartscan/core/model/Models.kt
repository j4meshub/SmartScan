package com.smartscan.core.model

data class UserProfile(
    val id: String,
    val username: String,
    val phoneMasked: String,
    val role: String,
    val status: String,
    val locale: String,
    val mustChangePassword: Boolean,
    val createdAt: String,
)

data class ScanProject(
    val id: String,
    val title: String,
    val suggestedName: String?,
    val mode: String,
    val readingOrder: String,
    val aiEnabled: Boolean = false,
    val aiConsentVersion: String? = null,
    val createdAt: String,
    val updatedAt: String,
)

data class AiCapabilities(
    val available: Boolean,
    val businessOrchestrationReady: Boolean,
    val executionMode: String,
    val consentVersion: String,
    val transmissionNoticeCode: String,
    val enhancementKinds: Set<String>,
    val taskTypes: Set<String>,
)

data class AiCandidate(
    val kind: String,
    val value: String,
    val confidence: Double?,
)

data class AiEnhancement(
    val id: String,
    val projectId: String,
    val pageId: String,
    val processingJobId: String?,
    val enhancementKind: String,
    val requestedTasks: List<String>,
    val sourceResultVersion: Int,
    val status: String,
    val candidates: List<AiCandidate>,
    val confidence: Double?,
    val errorCode: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class ScanPage(
    val id: String,
    val projectId: String,
    val pageNumber: Int,
    val reviewStatus: String,
    val qualityWarning: String?,
    val activeResultVersion: Int,
    val ocrStatus: String,
    val examResultVersion: Int? = null,
    val examConfidenceBand: String? = null,
    val examRecommendation: String? = null,
    val examSuggestionVisible: Boolean = false,
    val bookCaptureId: String? = null,
    val bookSide: String? = null,
    val bookSplitStatus: String = "disabled",
    val bookSplitConfidence: Double? = null,
    val bookSplitReason: String? = null,
    val bookDewarpApplied: Boolean? = null,
    val bookDewarpSourceScore: Double? = null,
    val bookDewarpOutputScore: Double? = null,
    val bookDewarpReason: String? = null,
    val bookReplacedByPageId: String? = null,
    val bookIsCurrent: Boolean = true,
    val bookPageNumberStatus: String = "disabled",
    val bookPageNumberLabel: String? = null,
    val bookPageNumberValue: Int? = null,
    val bookPageNumberKind: String? = null,
    val bookPageNumberConfidence: Double? = null,
    val bookPageNumberReason: String? = null,
    val bookPageNumberResultVersion: Int? = null,
    val bookExpectedPageLabel: String? = null,
    val bookContentFingerprint: String? = null,
    val bookFingerprintResultVersion: Int? = null,
    val bookAssemblyIncluded: Boolean = true,
    val bookAssemblyExclusionReason: String? = null,
)

data class BookIntegrityIssue(
    val key: String,
    val kind: String,
    val severity: String,
    val messageCode: String,
    val pageId: String?,
    val relatedPageId: String?,
    val printedPageLabel: String?,
    val decision: String?,
    val blocking: Boolean,
)

data class BookIntegrityReport(
    val projectId: String,
    val pagesChecked: Int,
    val includedPageCount: Int,
    val visiblePageNumberCount: Int,
    val processingPageCount: Int,
    val blockingIssueCount: Int,
    val readyToAssemble: Boolean,
    val issues: List<BookIntegrityIssue>,
)

data class ProcessingJob(
    val id: String,
    val projectId: String,
    val pageId: String?,
    val kind: String,
    val status: String,
    val progress: Int,
    val errorCode: String?,
    val updatedAt: String,
)

data class ExportArtifact(
    val id: String,
    val pageId: String?,
    val sequence: Int,
    val fileName: String,
    val mimeType: String,
    val sha256: String,
    val sizeBytes: Long,
)

data class ProjectExport(
    val id: String,
    val projectId: String,
    val format: String,
    val quality: String,
    val includeOcrText: Boolean,
    val status: String,
    val pageCount: Int,
    val errorCode: String?,
    val artifacts: List<ExportArtifact>,
    val createdAt: String,
    val bookAssemblySignature: String? = null,
    val bookAssemblyRevision: Int? = null,
    val bookPreviousExportId: String? = null,
)

data class DownloadedArtifact(
    val filePath: String,
    val fileName: String,
    val mimeType: String,
)

data class AccountDeletionReceipt(
    val id: String,
    val status: String,
    val requestedAt: String,
    val executeAfter: String,
)
