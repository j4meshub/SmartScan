package com.smartscan.data.repository

import com.smartscan.core.model.DownloadedArtifact
import com.smartscan.core.model.AiCandidate
import com.smartscan.core.model.AiCapabilities
import com.smartscan.core.model.AiEnhancement
import com.smartscan.core.model.BookIntegrityIssue
import com.smartscan.core.model.BookIntegrityReport
import com.smartscan.core.model.ExportArtifact
import com.smartscan.core.model.ProjectExport
import com.smartscan.core.model.ScanProject
import com.smartscan.core.model.ScanPage
import com.smartscan.core.network.ExportCreateRequestDto
import com.smartscan.core.network.ExportDto
import com.smartscan.core.network.AiApi
import com.smartscan.core.network.AiEnhancementDto
import com.smartscan.core.network.AiEnhancementRequestDto
import com.smartscan.core.network.ExamSuggestionDismissalRequestDto
import com.smartscan.core.network.BookAssemblyRequestDto
import com.smartscan.core.network.BookIntegrityDecisionRequestDto
import com.smartscan.core.network.BookIntegrityReportDto
import com.smartscan.core.network.PageCornerDto
import com.smartscan.core.network.PageEditRequestDto
import com.smartscan.core.network.PageOrderRequestDto
import com.smartscan.core.network.PageReviewRequestDto
import com.smartscan.core.network.PageRotationRequestDto
import com.smartscan.core.network.ProjectDto
import com.smartscan.core.network.ProjectAiSettingsRequestDto
import com.smartscan.core.network.ScanApi
import com.smartscan.core.network.WorkspaceApi
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

interface ProjectRepository {
    suspend fun listProjects(): ApiResult<List<ScanProject>>
    suspend fun listPages(projectId: String): ApiResult<List<ScanPage>>
    suspend fun reorderPages(projectId: String, pageIds: List<String>): ApiResult<List<ScanPage>>
    suspend fun rotatePage(pageId: String, degrees: Int): ApiResult<ScanPage>
    suspend fun editPage(pageId: String, corners: List<Pair<Double, Double>>, filter: String): ApiResult<ScanPage>
    suspend fun reviewPage(pageId: String, confirmed: Boolean): ApiResult<ScanPage>
    suspend fun dismissExamSuggestion(pageId: String, resultVersion: Int): ApiResult<ScanPage>
    suspend fun retakeBookSide(pageId: String, file: File, mimeType: String): ApiResult<ScanPage>
    suspend fun getBookIntegrity(projectId: String): ApiResult<BookIntegrityReport>
    suspend fun decideBookIntegrity(
        projectId: String,
        issueKey: String,
        decision: String,
    ): ApiResult<BookIntegrityReport>
    suspend fun supplementBookPage(
        projectId: String,
        file: File,
        mimeType: String,
        insertAt: Int,
        expectedPageLabel: String,
    ): ApiResult<ScanPage>
    suspend fun assembleBook(
        projectId: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport>
    suspend fun createExport(
        projectId: String,
        format: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport>
    suspend fun refreshExport(exportId: String): ApiResult<ProjectExport>
    suspend fun downloadPagePreview(pageId: String, directory: File, version: Int? = null): ApiResult<DownloadedArtifact>
    suspend fun downloadExportArtifact(artifact: ExportArtifact, directory: File): ApiResult<DownloadedArtifact>
    suspend fun getAiCapabilities(): ApiResult<AiCapabilities>
    suspend fun updateProjectAiSettings(
        projectId: String,
        enabled: Boolean,
        consentVersion: String?,
    ): ApiResult<ScanProject>
    suspend fun listAiEnhancements(pageId: String): ApiResult<List<AiEnhancement>>
    suspend fun requestAiEnhancement(
        pageId: String,
        enhancementKind: String,
        sourceResultVersion: Int,
        idempotencyKey: String = createAndroidAiIdempotencyKey(pageId, sourceResultVersion),
    ): ApiResult<AiEnhancement>
    suspend fun decideAiEnhancement(enhancementId: String, accept: Boolean): ApiResult<AiEnhancement>
}

class DefaultProjectRepository(
    private val api: ScanApi,
    private val workspaceApi: WorkspaceApi? = null,
    private val aiApi: AiApi? = null,
    private val cache: UserScopedCache? = null,
    private val currentUserId: () -> String? = { null },
) : ProjectRepository {
    override suspend fun listProjects(): ApiResult<List<ScanProject>> {
        val userId = currentUserId()
        return when (val remote = safeApiCall { api.listProjects().map { it.toModel() } }) {
            is ApiResult.Success -> {
                if (userId != null) runCatching { cache?.replaceProjects(userId, remote.value) }
                remote
            }
            is ApiResult.Failure -> {
                val cached = if (userId == null) null else runCatching { cache?.listProjects(userId) }.getOrNull()
                if (!cached.isNullOrEmpty()) ApiResult.Success(cached) else remote
            }
        }
    }

    override suspend fun listPages(projectId: String): ApiResult<List<ScanPage>> = withWorkspace {
        api.listPages(projectId).map { it.toModel() }
    }

    override suspend fun reorderPages(projectId: String, pageIds: List<String>): ApiResult<List<ScanPage>> = withWorkspace {
        require(pageIds.isNotEmpty() && pageIds.size == pageIds.toSet().size) { "page_order_invalid" }
        it.reorderPages(projectId, PageOrderRequestDto(pageIds)).map { page -> page.toModel() }
    }

    override suspend fun rotatePage(pageId: String, degrees: Int): ApiResult<ScanPage> = withWorkspace {
        require(degrees in setOf(90, 180, 270)) { "rotation_invalid" }
        it.rotatePage(pageId, PageRotationRequestDto(degrees)).toModel()
    }

    override suspend fun editPage(
        pageId: String,
        corners: List<Pair<Double, Double>>,
        filter: String,
    ): ApiResult<ScanPage> = withWorkspace {
        require(corners.size == 4 && corners.all { (x, y) -> x in 0.0..1.0 && y in 0.0..1.0 }) { "corners_invalid" }
        require(filter in setOf("original", "enhance", "grayscale", "bw")) { "filter_invalid" }
        it.editPage(pageId, PageEditRequestDto(corners.map { (x, y) -> PageCornerDto(x, y) }, filter)).toModel()
    }

    override suspend fun reviewPage(pageId: String, confirmed: Boolean): ApiResult<ScanPage> = withWorkspace {
        it.reviewPage(pageId, PageReviewRequestDto(if (confirmed) "confirmed" else "pending")).toModel()
    }

    override suspend fun dismissExamSuggestion(pageId: String, resultVersion: Int): ApiResult<ScanPage> = withWorkspace {
        require(resultVersion > 0) { "exam_result_version_invalid" }
        it.dismissExamSuggestion(pageId, ExamSuggestionDismissalRequestDto(resultVersion)).toModel()
    }

    override suspend fun retakeBookSide(
        pageId: String,
        file: File,
        mimeType: String,
    ): ApiResult<ScanPage> = withWorkspace {
        require(file.isFile && file.length() > 0) { "book_retake_file_invalid" }
        require(mimeType in setOf("image/jpeg", "image/png", "image/webp")) {
            "book_retake_mime_invalid"
        }
        val body = file.asRequestBody(mimeType.toMediaTypeOrNull())
        it.retakeBookSide(pageId, MultipartBody.Part.createFormData("file", file.name, body)).toModel()
    }

    override suspend fun getBookIntegrity(projectId: String): ApiResult<BookIntegrityReport> =
        withWorkspace { it.getBookIntegrity(projectId).toModel() }

    override suspend fun decideBookIntegrity(
        projectId: String,
        issueKey: String,
        decision: String,
    ): ApiResult<BookIntegrityReport> = withWorkspace {
        require(issueKey.isNotBlank()) { "book_integrity_issue_invalid" }
        require(
            decision in setOf(
                "ignored",
                "confirmed_absent",
                "keep_both",
                "exclude_duplicate",
                "reopen",
            ),
        ) { "book_integrity_decision_invalid" }
        it.decideBookIntegrity(projectId, BookIntegrityDecisionRequestDto(issueKey, decision)).toModel()
    }

    override suspend fun supplementBookPage(
        projectId: String,
        file: File,
        mimeType: String,
        insertAt: Int,
        expectedPageLabel: String,
    ): ApiResult<ScanPage> = withWorkspace {
        require(file.isFile && file.length() > 0) { "book_supplement_file_invalid" }
        require(mimeType in setOf("image/jpeg", "image/png", "image/webp")) {
            "book_supplement_mime_invalid"
        }
        require(insertAt > 0 && expectedPageLabel.isNotBlank()) { "book_supplement_position_invalid" }
        val body = file.asRequestBody(mimeType.toMediaTypeOrNull())
        it.supplementBookPage(
            projectId,
            MultipartBody.Part.createFormData("file", file.name, body),
            insertAt.toString().toRequestBody("text/plain".toMediaTypeOrNull()),
            expectedPageLabel.toRequestBody("text/plain".toMediaTypeOrNull()),
        ).toModel()
    }

    override suspend fun assembleBook(
        projectId: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport> = withWorkspace {
        require(quality in setOf("clear", "balanced", "small")) { "export_quality_invalid" }
        it.assembleBook(projectId, BookAssemblyRequestDto(quality, includeOcrText)).toModel()
    }

    override suspend fun createExport(
        projectId: String,
        format: String,
        quality: String,
        includeOcrText: Boolean,
    ): ApiResult<ProjectExport> = withWorkspace {
        require(format in setOf("jpg", "pdf")) { "export_format_invalid" }
        require(quality in setOf("clear", "balanced", "small")) { "export_quality_invalid" }
        it.createExport(projectId, ExportCreateRequestDto(format, quality, includeOcrText)).toModel()
    }

    override suspend fun refreshExport(exportId: String): ApiResult<ProjectExport> = withWorkspace {
        it.getExport(exportId).toModel()
    }

    override suspend fun downloadPagePreview(
        pageId: String,
        directory: File,
        version: Int?,
    ): ApiResult<DownloadedArtifact> = withWorkspace {
        require(version == null || version > 0) { "page_result_version_invalid" }
        withContext(Dispatchers.IO) {
            val versionSuffix = version?.let { value -> "-v$value" } ?: "-active"
            val stableName = "page-${sha256(pageId.toByteArray()).take(16)}$versionSuffix.img"
            saveDownload(it.downloadPageContent(pageId, version = version), directory, stableName, null, null)
        }
    }

    override suspend fun downloadExportArtifact(
        artifact: ExportArtifact,
        directory: File,
    ): ApiResult<DownloadedArtifact> = withWorkspace {
        withContext(Dispatchers.IO) {
            saveDownload(
                body = it.downloadExportArtifact(artifact.id),
                directory = directory,
                requestedName = "${artifact.id.take(12)}-${artifact.fileName}",
                displayName = artifact.fileName,
                expectedSha256 = artifact.sha256,
                fallbackMimeType = artifact.mimeType,
                expectedSize = artifact.sizeBytes,
            )
        }
    }

    override suspend fun getAiCapabilities(): ApiResult<AiCapabilities> = withAi {
        it.getAiCapabilities().let { dto ->
            AiCapabilities(
                available = dto.available,
                businessOrchestrationReady = dto.businessOrchestrationReady,
                executionMode = dto.executionMode,
                consentVersion = dto.consentVersion,
                transmissionNoticeCode = dto.transmissionNoticeCode,
                enhancementKinds = dto.enhancementKinds.toSet(),
                taskTypes = dto.taskTypes.toSet(),
            )
        }
    }

    override suspend fun updateProjectAiSettings(
        projectId: String,
        enabled: Boolean,
        consentVersion: String?,
    ): ApiResult<ScanProject> = withAi {
        require(!enabled || !consentVersion.isNullOrBlank()) { "ai_consent_required" }
        it.updateProjectAiSettings(
            projectId,
            ProjectAiSettingsRequestDto(enabled = enabled, consentVersion = if (enabled) consentVersion else null),
        ).toModel()
    }

    override suspend fun listAiEnhancements(pageId: String): ApiResult<List<AiEnhancement>> = withAi {
        it.listAiEnhancements(pageId).map(AiEnhancementDto::toModel)
    }

    override suspend fun requestAiEnhancement(
        pageId: String,
        enhancementKind: String,
        sourceResultVersion: Int,
        idempotencyKey: String,
    ): ApiResult<AiEnhancement> = withAi {
        require(enhancementKind in setOf("recommended", "complex_ocr")) { "ai_enhancement_kind_invalid" }
        require(sourceResultVersion > 0) { "ai_source_version_invalid" }
        require(idempotencyKey.length in 16..100) { "ai_idempotency_key_invalid" }
        it.createAiEnhancement(
            pageId,
            idempotencyKey,
            AiEnhancementRequestDto(enhancementKind, sourceResultVersion),
        ).toModel()
    }

    override suspend fun decideAiEnhancement(
        enhancementId: String,
        accept: Boolean,
    ): ApiResult<AiEnhancement> = withAi {
        require(enhancementId.isNotBlank()) { "ai_enhancement_id_invalid" }
        (if (accept) it.acceptAiEnhancement(enhancementId) else it.rejectAiEnhancement(enhancementId)).toModel()
    }

    private suspend fun <T> withWorkspace(block: suspend (WorkspaceApi) -> T): ApiResult<T> {
        val endpoint = workspaceApi ?: return ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
        return safeApiCall { block(endpoint) }
    }

    private suspend fun <T> withAi(block: suspend (AiApi) -> T): ApiResult<T> {
        val endpoint = aiApi ?: return ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
        return safeApiCall { block(endpoint) }
    }
}

private fun ProjectDto.toModel() = ScanProject(
    id = id,
    title = title,
    suggestedName = suggestedName,
    mode = mode,
    readingOrder = readingOrder,
    aiEnabled = aiEnabled,
    aiConsentVersion = aiConsentVersion,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun AiEnhancementDto.toModel() = AiEnhancement(
    id = id,
    projectId = projectId,
    pageId = pageId,
    processingJobId = processingJobId,
    enhancementKind = enhancementKind,
    requestedTasks = requestedTasks,
    sourceResultVersion = sourceResultVersion,
    status = status,
    candidates = parseAiCandidates(candidateResult as? JsonObject),
    confidence = confidence,
    errorCode = errorCode,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

internal fun createAndroidAiIdempotencyKey(
    pageId: String,
    sourceResultVersion: Int,
    randomId: String = UUID.randomUUID().toString(),
): String {
    require(sourceResultVersion > 0) { "ai_source_version_invalid" }
    val safePage = pageId.replace(Regex("[^A-Za-z0-9_.:-]"), "_").take(24).ifBlank { "page" }
    return "android-ai.$safePage.v$sourceResultVersion.$randomId".take(100)
}

internal fun parseAiCandidates(candidateResult: JsonObject?): List<AiCandidate> {
    val tasks = candidateResult?.get("tasks") as? JsonObject ?: return emptyList()
    return buildList {
        val classification = tasks["classify_page"] as? JsonObject
        classification.string("label")?.let {
            add(AiCandidate("classification", it.preview(), classification.confidence()))
        }
        val orientation = tasks["detect_orientation"] as? JsonObject
        orientation?.int("rotation_degrees")?.takeIf { it in setOf(0, 90, 180, 270) }?.let {
            add(AiCandidate("orientation", it.toString(), orientation.confidence()))
        }
        val title = ((tasks["extract_title"] as? JsonObject)?.get("candidates") as? JsonArray)
            ?.mapNotNull { it as? JsonObject }
            ?.filter { !it.string("text").isNullOrBlank() }
            ?.maxByOrNull { it.confidence() ?: 0.0 }
        title?.string("text")?.let { add(AiCandidate("title", it.preview(), title.confidence())) }
        val pageNumber = tasks["extract_page_number"] as? JsonObject
        if (pageNumber.string("status") == "detected") {
            val value = pageNumber.string("raw_label") ?: pageNumber.int("normalized_number")?.toString()
            value?.let { add(AiCandidate("page_number", it.preview(), pageNumber.confidence())) }
        }
        val blocks = (((tasks["ocr_formula"] as? JsonObject)?.get("blocks") as? JsonArray)
            ?.take(40)).orEmpty()
        for (element in blocks) {
            val block = element as? JsonObject ?: continue
            when (block.string("block_type")) {
                "formula" -> block.string("latex_candidate")?.let {
                    add(AiCandidate("formula", it.preview(), block.confidence()))
                }
                "layout" -> block.string("text_candidate")?.let {
                    add(AiCandidate("layout", it.preview(), block.confidence()))
                }
                "table" -> {
                    val rows = sortedMapOf<Int, MutableList<Pair<Int, String>>>()
                    val cells = (block["cells"] as? JsonArray)?.take(200).orEmpty()
                    for (cellElement in cells) {
                        val cell = cellElement as? JsonObject ?: continue
                        val row = cell.int("row") ?: continue
                        val column = cell.int("column") ?: continue
                        val text = cell.string("text_candidate")?.trim().orEmpty()
                        if (row < 0 || column < 0 || text.isBlank()) continue
                        rows.getOrPut(row) { mutableListOf() }.add(column to text)
                    }
                    val text = rows.values.joinToString(" / ") { row ->
                        row.sortedBy { it.first }.joinToString(" | ") { it.second }
                    }.preview()
                    if (text.isNotBlank()) add(AiCandidate("table", text, block.confidence()))
                }
            }
        }
    }
}

private fun JsonObject?.string(name: String): String? = ((this?.get(name) as? JsonPrimitive)?.contentOrNull)
    ?.trim()?.takeIf(String::isNotEmpty)
private fun JsonObject?.int(name: String): Int? = (this?.get(name) as? JsonPrimitive)?.intOrNull
private fun JsonObject?.confidence(): Double? = (this?.get("confidence") as? JsonPrimitive)?.doubleOrNull
    ?.takeIf { it in 0.0..1.0 }
private fun String.preview(): String = trim().take(512)

private fun com.smartscan.core.network.PageDto.toModel() = ScanPage(
    id = id,
    projectId = projectId,
    pageNumber = pageNumber,
    reviewStatus = reviewStatus,
    qualityWarning = qualityWarning,
    activeResultVersion = activeResultVersion,
    ocrStatus = ocrStatus,
    examResultVersion = examResultVersion,
    examConfidenceBand = examConfidenceBand,
    examRecommendation = examRecommendation,
    examSuggestionVisible = examSuggestionVisible,
    bookCaptureId = bookCaptureId,
    bookSide = bookSide,
    bookSplitStatus = bookSplitStatus,
    bookSplitConfidence = bookSplitConfidence,
    bookSplitReason = bookSplitReason,
    bookDewarpApplied = bookDewarpApplied,
    bookDewarpSourceScore = bookDewarpSourceScore,
    bookDewarpOutputScore = bookDewarpOutputScore,
    bookDewarpReason = bookDewarpReason,
    bookReplacedByPageId = bookReplacedByPageId,
    bookIsCurrent = bookIsCurrent,
    bookPageNumberStatus = bookPageNumberStatus,
    bookPageNumberLabel = bookPageNumberLabel,
    bookPageNumberValue = bookPageNumberValue,
    bookPageNumberKind = bookPageNumberKind,
    bookPageNumberConfidence = bookPageNumberConfidence,
    bookPageNumberReason = bookPageNumberReason,
    bookPageNumberResultVersion = bookPageNumberResultVersion,
    bookExpectedPageLabel = bookExpectedPageLabel,
    bookContentFingerprint = bookContentFingerprint,
    bookFingerprintResultVersion = bookFingerprintResultVersion,
    bookAssemblyIncluded = bookAssemblyIncluded,
    bookAssemblyExclusionReason = bookAssemblyExclusionReason,
)

private fun BookIntegrityReportDto.toModel() = BookIntegrityReport(
    projectId = projectId,
    pagesChecked = pagesChecked,
    includedPageCount = includedPageCount,
    visiblePageNumberCount = visiblePageNumberCount,
    processingPageCount = processingPageCount,
    blockingIssueCount = blockingIssueCount,
    readyToAssemble = readyToAssemble,
    issues = issues.map {
        BookIntegrityIssue(
            key = it.key,
            kind = it.kind,
            severity = it.severity,
            messageCode = it.messageCode,
            pageId = it.pageId,
            relatedPageId = it.relatedPageId,
            printedPageLabel = it.printedPageLabel,
            decision = it.decision,
            blocking = it.blocking,
        )
    },
)

private fun ExportDto.toModel() = ProjectExport(
    id = id,
    projectId = projectId,
    format = format,
    quality = quality,
    includeOcrText = includeOcrText,
    status = status,
    pageCount = pageCount,
    errorCode = errorCode,
    artifacts = artifacts.map {
        ExportArtifact(it.id, it.pageId, it.sequence, it.fileName, it.mimeType, it.sha256, it.sizeBytes)
    },
    createdAt = createdAt,
    bookAssemblySignature = bookAssemblySignature,
    bookAssemblyRevision = bookAssemblyRevision,
    bookPreviousExportId = bookPreviousExportId,
)

private fun saveDownload(
    body: okhttp3.ResponseBody,
    directory: File,
    requestedName: String,
    expectedSha256: String?,
    fallbackMimeType: String?,
    expectedSize: Long? = null,
    displayName: String = requestedName,
): DownloadedArtifact {
    require(directory.mkdirs() || directory.isDirectory) { "download_directory_unavailable" }
    val safeName = File(requestedName).name.trim().takeIf { it.isNotEmpty() && it !in setOf(".", "..") }
        ?: throw IllegalArgumentException("download_name_invalid")
    val root = directory.canonicalFile
    val destination = File(root, safeName).canonicalFile
    require(destination.parentFile == root) { "download_path_invalid" }
    val temporary = File(root, ".${safeName}.${UUID.randomUUID()}.part")
    val digest = MessageDigest.getInstance("SHA-256")
    var written = 0L
    try {
        body.use { response ->
            response.byteStream().use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                        written += count
                    }
                }
            }
            expectedSize?.let { require(written == it) { "download_size_mismatch" } }
            expectedSha256?.let { require(digest.digest().toHex() == it) { "download_hash_mismatch" } }
            if (destination.exists() && !destination.delete()) throw IOException("download_replace_failed")
            if (!temporary.renameTo(destination)) throw IOException("download_commit_failed")
            return DownloadedArtifact(
                filePath = destination.absolutePath,
                fileName = File(displayName).name,
                mimeType = response.contentType()?.toString() ?: fallbackMimeType ?: "application/octet-stream",
            )
        }
    } catch (failure: Exception) {
        temporary.delete()
        throw failure
    }
}

private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).toHex()
private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xFF) }

internal suspend fun <T> safeApiCall(block: suspend () -> T): ApiResult<T> = try {
    ApiResult.Success(block())
} catch (error: HttpException) {
    val status = error.code()
    val kind = when (status) {
        401 -> FailureKind.UNAUTHORIZED
        404 -> FailureKind.NOT_FOUND
        429 -> FailureKind.RATE_LIMITED
        in 500..599 -> FailureKind.SERVER
        else -> FailureKind.UNKNOWN
    }
    ApiResult.Failure(kind, statusCode = status, retryable = status == 429 || status >= 500)
} catch (_: IOException) {
    ApiResult.Failure(FailureKind.NETWORK, retryable = true)
} catch (_: SerializationException) {
    ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
} catch (_: IllegalArgumentException) {
    ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
}
