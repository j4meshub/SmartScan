package com.smartscan.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import retrofit2.http.GET
import retrofit2.http.Path

interface SmartScanApi {
    @GET("v1/projects")
    suspend fun listProjects(): List<ProjectDto>

    @GET("v1/projects/{projectId}/pages")
    suspend fun listPages(@Path("projectId") projectId: String): List<PageDto>

    @GET("v1/jobs")
    suspend fun listJobs(): List<JobDto>

    @GET("v1/projects/{projectId}/exports")
    suspend fun listExports(@Path("projectId") projectId: String): List<ExportDto>
}

@Serializable
data class ProjectDto(
    val id: String,
    @SerialName("owner_user_id") val ownerUserId: String,
    val title: String,
    @SerialName("suggested_name") val suggestedName: String? = null,
    @SerialName("suggested_name_source") val suggestedNameSource: String? = null,
    val mode: String,
    @SerialName("reading_order") val readingOrder: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class PageDto(
    val id: String,
    @SerialName("project_id") val projectId: String,
    @SerialName("page_number") val pageNumber: Int,
    @SerialName("quality_warning") val qualityWarning: String? = null,
    @SerialName("quality_details") val qualityDetails: JsonElement? = null,
    @SerialName("active_result_version") val activeResultVersion: Int,
    @SerialName("review_status") val reviewStatus: String,
    @SerialName("ocr_status") val ocrStatus: String,
)

@Serializable
data class JobDto(
    val id: String,
    @SerialName("project_id") val projectId: String,
    @SerialName("page_id") val pageId: String? = null,
    val kind: String,
    val status: String,
    val progress: Int,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class ExportArtifactDto(
    val id: String,
    @SerialName("file_name") val fileName: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

@Serializable
data class ExportDto(
    val id: String,
    @SerialName("project_id") val projectId: String,
    val format: String,
    val quality: String,
    val status: String,
    val artifacts: List<ExportArtifactDto>,
    @SerialName("created_at") val createdAt: String,
)
