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
