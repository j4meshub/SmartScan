package com.smartscan.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import okhttp3.RequestBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Path
import retrofit2.http.POST
import retrofit2.http.PUT

interface SmartScanApi : AuthenticationApi, ScanApi

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
