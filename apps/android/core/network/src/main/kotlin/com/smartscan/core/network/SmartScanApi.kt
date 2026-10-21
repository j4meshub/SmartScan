package com.smartscan.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import okhttp3.RequestBody
import okhttp3.ResponseBody
import retrofit2.http.Streaming
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.Path
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Query

interface SmartScanApi : AuthenticationApi, ScanApi, WorkspaceApi

interface AuthenticationApi {
    @POST("v1/auth/sms-challenges")
    suspend fun requestSmsChallenge(@Body request: SmsChallengeRequestDto): SmsChallengeDto

    @POST("v1/auth/register")
    suspend fun register(@Body request: RegisterRequestDto): TokenDto

    @POST("v1/auth/login")
    suspend fun login(@Body request: LoginRequestDto): TokenDto

    @POST("v1/auth/refresh")
    suspend fun refresh(@Body request: RefreshRequestDto): TokenDto

    @POST("v1/auth/logout")
    suspend fun logout()

    @GET("v1/me")
    suspend fun me(): UserDto

    @POST("v1/me/account-deletion")
    suspend fun requestAccountDeletion(@Body request: AccountDeletionRequestDto): AccountDeletionDto

    @POST("v1/auth/account-deletion/cancel")
    suspend fun cancelAccountDeletion(@Body request: AccountDeletionRequestDto): AccountDeletionDto
}

interface ScanApi {
    @POST("v1/projects")
    suspend fun createProject(@Body request: CreateProjectRequestDto): ProjectDto

    @GET("v1/projects")
    suspend fun listProjects(): List<ProjectDto>

    @GET("v1/projects/{projectId}/pages")
    suspend fun listPages(@Path("projectId") projectId: String): List<PageDto>

    @GET("v1/jobs")
    suspend fun listJobs(): List<JobDto>

    @GET("v1/projects/{projectId}/exports")
    suspend fun listExports(@Path("projectId") projectId: String): List<ExportDto>

    @POST("v1/uploads")
    suspend fun createUpload(@Body request: CreateUploadRequestDto): UploadDto

    @GET("v1/uploads/{uploadId}")
    suspend fun getUpload(@Path("uploadId") uploadId: String): UploadDto

    @PUT("v1/uploads/{uploadId}/chunks/{chunkIndex}")
    suspend fun putUploadChunk(
        @Path("uploadId") uploadId: String,
        @Path("chunkIndex") chunkIndex: Int,
        @Header("X-Chunk-Sha256") chunkSha256: String,
        @Body body: RequestBody,
    ): ChunkReceiptDto

    @POST("v1/uploads/{uploadId}/complete")
    suspend fun completeUpload(@Path("uploadId") uploadId: String): PageDto
}

interface WorkspaceApi {
    @PATCH("v1/projects/{projectId}/pages/order")
    suspend fun reorderPages(
        @Path("projectId") projectId: String,
        @Body request: PageOrderRequestDto,
    ): List<PageDto>

    @POST("v1/pages/{pageId}/rotations")
    suspend fun rotatePage(@Path("pageId") pageId: String, @Body request: PageRotationRequestDto): PageDto

    @POST("v1/pages/{pageId}/edits")
    suspend fun editPage(@Path("pageId") pageId: String, @Body request: PageEditRequestDto): PageDto

    @PATCH("v1/pages/{pageId}/review")
    suspend fun reviewPage(@Path("pageId") pageId: String, @Body request: PageReviewRequestDto): PageDto

    @PUT("v1/pages/{pageId}/exam-suggestion-dismissal")
    suspend fun dismissExamSuggestion(
        @Path("pageId") pageId: String,
        @Body request: ExamSuggestionDismissalRequestDto,
    ): PageDto

    @POST("v1/projects/{projectId}/exports")
    suspend fun createExport(
        @Path("projectId") projectId: String,
        @Body request: ExportCreateRequestDto,
    ): ExportDto

    @GET("v1/exports/{exportId}")
    suspend fun getExport(@Path("exportId") exportId: String): ExportDto

    @Streaming
    @GET("v1/pages/{pageId}/content")
    suspend fun downloadPageContent(
        @Path("pageId") pageId: String,
        @Query("variant") variant: String = "active",
    ): ResponseBody

    @Streaming
    @GET("v1/export-artifacts/{artifactId}/content")
    suspend fun downloadExportArtifact(@Path("artifactId") artifactId: String): ResponseBody
}

@Serializable
data class AccountDeletionRequestDto(
    val phone: String,
    @SerialName("sms_challenge_id") val smsChallengeId: String,
    @SerialName("sms_code") val smsCode: String,
)

@Serializable
data class AccountDeletionDto(
    val id: String,
    val status: String,
    @SerialName("requested_at") val requestedAt: String,
    @SerialName("execute_after") val executeAfter: String,
    @SerialName("canceled_at") val canceledAt: String? = null,
    @SerialName("completed_at") val completedAt: String? = null,
)

@Serializable
data class CreateProjectRequestDto(
    val title: String,
    val mode: String,
    @SerialName("reading_order") val readingOrder: String = "ltr",
)

@Serializable
data class CreateUploadRequestDto(
    @SerialName("project_id") val projectId: String,
    @SerialName("file_name") val fileName: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val sha256: String,
    @SerialName("idempotency_key") val idempotencyKey: String,
)

@Serializable
data class UploadDto(
    val id: String,
    @SerialName("project_id") val projectId: String,
    @SerialName("file_name") val fileName: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    @SerialName("chunk_size") val chunkSize: Long,
    @SerialName("total_chunks") val totalChunks: Int,
    @SerialName("received_chunks") val receivedChunks: List<Int>,
    val status: String,
    @SerialName("page_id") val pageId: String? = null,
    @SerialName("expires_at") val expiresAt: String,
)

@Serializable
data class ChunkReceiptDto(
    @SerialName("upload_id") val uploadId: String,
    @SerialName("chunk_index") val chunkIndex: Int,
    @SerialName("size_bytes") val sizeBytes: Long,
    val sha256: String,
)

@Serializable
data class PageOrderRequestDto(@SerialName("page_ids") val pageIds: List<String>)

@Serializable
data class PageRotationRequestDto(val degrees: Int)

@Serializable
data class PageCornerDto(val x: Double, val y: Double)

@Serializable
data class PageEditRequestDto(
    val corners: List<PageCornerDto>? = null,
    val filter: String = "original",
)

@Serializable
data class PageReviewRequestDto(
    val status: String,
    val note: String? = null,
)

@Serializable
data class ExamSuggestionDismissalRequestDto(
    @SerialName("result_version") val resultVersion: Int,
    val reason: String = "user_dismissed",
)

@Serializable
data class ExportCreateRequestDto(
    val format: String,
    val quality: String = "balanced",
    @SerialName("include_ocr_text") val includeOcrText: Boolean = false,
    @SerialName("page_ids") val pageIds: List<String>? = null,
)

@Serializable
data class SmsChallengeRequestDto(
    val phone: String,
    val purpose: String = "registration",
)

@Serializable
data class SmsChallengeDto(
    @SerialName("challenge_id") val challengeId: String,
    @SerialName("expires_at") val expiresAt: String,
    @SerialName("retry_after_seconds") val retryAfterSeconds: Int,
)

@Serializable
data class RegisterRequestDto(
    val phone: String,
    @SerialName("sms_code") val smsCode: String,
    @SerialName("sms_challenge_id") val smsChallengeId: String? = null,
    val username: String,
    val password: String,
    val locale: String,
)

@Serializable
data class LoginRequestDto(
    val username: String,
    val password: String,
)

@Serializable
data class RefreshRequestDto(
    @SerialName("refresh_token") val refreshToken: String,
)

@Serializable
data class TokenDto(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String,
    @SerialName("expires_at") val expiresAt: String,
    @SerialName("refresh_token") val refreshToken: String? = null,
    @SerialName("refresh_expires_at") val refreshExpiresAt: String? = null,
    @SerialName("session_id") val sessionId: String? = null,
    @SerialName("device_id") val deviceId: String? = null,
)

@Serializable
data class UserDto(
    val id: String,
    val username: String,
    @SerialName("phone_masked") val phoneMasked: String,
    val role: String,
    val status: String,
    val locale: String,
    @SerialName("must_change_password") val mustChangePassword: Boolean,
    @SerialName("created_at") val createdAt: String,
)

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
    @SerialName("exam_result_version") val examResultVersion: Int? = null,
    @SerialName("exam_confidence_band") val examConfidenceBand: String? = null,
    @SerialName("exam_recommendation") val examRecommendation: String? = null,
    @SerialName("exam_suggestion_visible") val examSuggestionVisible: Boolean = false,
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
    @SerialName("page_id") val pageId: String? = null,
    val sequence: Int = 1,
    @SerialName("file_name") val fileName: String,
    @SerialName("mime_type") val mimeType: String,
    val sha256: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

@Serializable
data class ExportDto(
    val id: String,
    @SerialName("project_id") val projectId: String,
    val format: String,
    val quality: String,
    @SerialName("include_ocr_text") val includeOcrText: Boolean = false,
    val status: String,
    @SerialName("page_count") val pageCount: Int = 0,
    @SerialName("error_code") val errorCode: String? = null,
    val artifacts: List<ExportArtifactDto>,
    @SerialName("created_at") val createdAt: String,
)
