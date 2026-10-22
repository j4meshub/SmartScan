import Foundation

struct WorkspaceProject: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: String
    let title: String
    let suggestedName: String?
    let mode: String
    let readingOrder: String
    let createdAt: String
    let updatedAt: String
    var aiEnabled: Bool? = nil
    var aiConsentVersion: String? = nil

    var displayName: String { suggestedName ?? title }
    var isAIEnabled: Bool { aiEnabled == true }

    enum CodingKeys: String, CodingKey {
        case id, title, mode
        case suggestedName = "suggested_name"
        case readingOrder = "reading_order"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case aiEnabled = "ai_enabled"
        case aiConsentVersion = "ai_consent_version"
    }
}

struct WorkspaceAICapabilities: Codable, Equatable, Sendable {
    let available: Bool
    let businessOrchestrationReady: Bool
    let executionMode: String
    let consentVersion: String
    let transmissionNoticeCode: String
    let enhancementKinds: Set<String>
    let taskTypes: Set<String>

    enum CodingKeys: String, CodingKey {
        case available
        case businessOrchestrationReady = "business_orchestration_ready"
        case executionMode = "execution_mode"
        case consentVersion = "consent_version"
        case transmissionNoticeCode = "transmission_notice_code"
        case enhancementKinds = "enhancement_kinds"
        case taskTypes = "task_types"
    }
}

struct WorkspaceAICandidate: Equatable, Sendable, Identifiable {
    let kind: String
    let value: String
    let confidence: Double?

    var id: String { "\(kind):\(value)" }
}

struct WorkspaceAIEnhancement: Decodable, Equatable, Sendable, Identifiable {
    let id: String
    let projectID: String
    let pageID: String
    let processingJobID: String?
    let enhancementKind: String
    let requestedTasks: [String]
    let sourceResultVersion: Int
    let status: String
    let candidates: [WorkspaceAICandidate]
    let confidence: Double?
    let errorCode: String?
    let createdAt: String
    let updatedAt: String

    init(
        id: String,
        projectID: String,
        pageID: String,
        processingJobID: String?,
        enhancementKind: String,
        requestedTasks: [String],
        sourceResultVersion: Int,
        status: String,
        candidates: [WorkspaceAICandidate],
        confidence: Double?,
        errorCode: String?,
        createdAt: String,
        updatedAt: String
    ) {
        self.id = id
        self.projectID = projectID
        self.pageID = pageID
        self.processingJobID = processingJobID
        self.enhancementKind = enhancementKind
        self.requestedTasks = requestedTasks
        self.sourceResultVersion = sourceResultVersion
        self.status = status
        self.candidates = candidates
        self.confidence = confidence
        self.errorCode = errorCode
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        projectID = try container.decode(String.self, forKey: .projectID)
        pageID = try container.decode(String.self, forKey: .pageID)
        processingJobID = try container.decodeIfPresent(String.self, forKey: .processingJobID)
        enhancementKind = try container.decode(String.self, forKey: .enhancementKind)
        requestedTasks = try container.decode([String].self, forKey: .requestedTasks)
        sourceResultVersion = try container.decode(Int.self, forKey: .sourceResultVersion)
        status = try container.decode(String.self, forKey: .status)
        let result = try container.decodeIfPresent(WorkspaceAICandidateEnvelope.self, forKey: .candidateResult)
        candidates = workspaceAICandidates(from: result)
        confidence = validAIConfidence(try container.decodeIfPresent(Double.self, forKey: .confidence))
        errorCode = try container.decodeIfPresent(String.self, forKey: .errorCode)
        createdAt = try container.decode(String.self, forKey: .createdAt)
        updatedAt = try container.decode(String.self, forKey: .updatedAt)
    }

    private enum CodingKeys: String, CodingKey {
        case id, status, confidence
        case projectID = "project_id"
        case pageID = "page_id"
        case processingJobID = "processing_job_id"
        case enhancementKind = "enhancement_kind"
        case requestedTasks = "requested_tasks"
        case sourceResultVersion = "source_result_version"
        case candidateResult = "candidate_result"
        case errorCode = "error_code"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

private struct WorkspaceAICandidateEnvelope: Decodable {
    let tasks: WorkspaceAITasks?
}

private struct WorkspaceAITasks: Decodable {
    let classifyPage: WorkspaceAIClassification?
    let detectOrientation: WorkspaceAIOrientation?
    let extractTitle: WorkspaceAITitleResult?
    let extractPageNumber: WorkspaceAIPageNumber?
    let ocrFormula: WorkspaceAIFormulaResult?

    enum CodingKeys: String, CodingKey {
        case classifyPage = "classify_page"
        case detectOrientation = "detect_orientation"
        case extractTitle = "extract_title"
        case extractPageNumber = "extract_page_number"
        case ocrFormula = "ocr_formula"
    }
}

private struct WorkspaceAIClassification: Decodable {
    let label: String?
    let confidence: Double?
}

private struct WorkspaceAIOrientation: Decodable {
    let rotationDegrees: Int?
    let confidence: Double?

    enum CodingKeys: String, CodingKey {
        case confidence
        case rotationDegrees = "rotation_degrees"
    }
}

private struct WorkspaceAITitleResult: Decodable {
    let candidates: [WorkspaceAITitleCandidate]?
}

private struct WorkspaceAITitleCandidate: Decodable {
    let text: String?
    let confidence: Double?
}

private struct WorkspaceAIPageNumber: Decodable {
    let status: String?
    let rawLabel: String?
    let normalizedNumber: Int?
    let confidence: Double?

    enum CodingKeys: String, CodingKey {
        case status, confidence
        case rawLabel = "raw_label"
        case normalizedNumber = "normalized_number"
    }
}

private struct WorkspaceAIFormulaResult: Decodable {
    let blocks: [WorkspaceAIBlock]?
}

private struct WorkspaceAIBlock: Decodable {
    let blockType: String?
    let latexCandidate: String?
    let textCandidate: String?
    let cells: [WorkspaceAITableCell]?
    let confidence: Double?

    enum CodingKeys: String, CodingKey {
        case cells, confidence
        case blockType = "block_type"
        case latexCandidate = "latex_candidate"
        case textCandidate = "text_candidate"
    }
}

private struct WorkspaceAITableCell: Decodable {
    let row: Int?
    let column: Int?
    let textCandidate: String?

    enum CodingKeys: String, CodingKey {
        case row, column
        case textCandidate = "text_candidate"
    }
}

private func workspaceAICandidates(from envelope: WorkspaceAICandidateEnvelope?) -> [WorkspaceAICandidate] {
    guard let tasks = envelope?.tasks else { return [] }
    var candidates: [WorkspaceAICandidate] = []
    if let classification = aiPreview(tasks.classifyPage?.label) {
        candidates.append(.init(
            kind: "classification",
            value: classification,
            confidence: validAIConfidence(tasks.classifyPage?.confidence)
        ))
    }
    if let orientation = tasks.detectOrientation,
       let degrees = orientation.rotationDegrees,
       [0, 90, 180, 270].contains(degrees) {
        candidates.append(.init(
            kind: "orientation",
            value: String(degrees),
            confidence: validAIConfidence(orientation.confidence)
        ))
    }
    let title = tasks.extractTitle?.candidates?
        .filter { aiPreview($0.text) != nil }
        .max { (validAIConfidence($0.confidence) ?? 0) < (validAIConfidence($1.confidence) ?? 0) }
    if let value = aiPreview(title?.text) {
        candidates.append(.init(kind: "title", value: value, confidence: validAIConfidence(title?.confidence)))
    }
    if tasks.extractPageNumber?.status == "detected" {
        let pageNumber = aiPreview(tasks.extractPageNumber?.rawLabel)
            ?? tasks.extractPageNumber?.normalizedNumber.map { String($0) }
        if let pageNumber {
            candidates.append(.init(
                kind: "page_number",
                value: pageNumber,
                confidence: validAIConfidence(tasks.extractPageNumber?.confidence)
            ))
        }
    }
    for block in (tasks.ocrFormula?.blocks ?? []).prefix(40) {
        let confidence = validAIConfidence(block.confidence)
        switch block.blockType {
        case "formula":
            if let value = aiPreview(block.latexCandidate) {
                candidates.append(.init(kind: "formula", value: value, confidence: confidence))
            }
        case "layout":
            if let value = aiPreview(block.textCandidate) {
                candidates.append(.init(kind: "layout", value: value, confidence: confidence))
            }
        case "table":
            var rows: [Int: [(Int, String)]] = [:]
            for cell in (block.cells ?? []).prefix(200) {
                guard let row = cell.row, row >= 0,
                      let column = cell.column, column >= 0,
                      let text = aiPreview(cell.textCandidate) else { continue }
                rows[row, default: []].append((column, text))
            }
            let table = rows.keys.sorted().map { row in
                rows[row, default: []].sorted { $0.0 < $1.0 }.map { $0.1 }.joined(separator: " | ")
            }.joined(separator: " / ")
            if let value = aiPreview(table) {
                candidates.append(.init(kind: "table", value: value, confidence: confidence))
            }
        default: break
        }
    }
    return candidates
}

private func validAIConfidence(_ value: Double?) -> Double? {
    guard let value, value.isFinite, (0 ... 1).contains(value) else { return nil }
    return value
}

private func aiPreview(_ value: String?) -> String? {
    guard let value else { return nil }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    return String(trimmed.prefix(512))
}

struct WorkspacePage: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: String
    let projectID: String
    let pageNumber: Int
    let qualityWarning: String?
    let rotationDegrees: Int
    let activeResultVersion: Int
    let reviewStatus: String
    let ocrStatus: String
    let examResultVersion: Int?
    let examConfidenceBand: String?
    let examRecommendation: String?
    let examSuggestionVisible: Bool?
    var bookCaptureID: String? = nil
    var bookSide: String? = nil
    var bookSplitStatus: String? = nil
    var bookSplitConfidence: Double? = nil
    var bookSplitReason: String? = nil
    var bookDewarpApplied: Bool? = nil
    var bookDewarpSourceScore: Double? = nil
    var bookDewarpOutputScore: Double? = nil
    var bookDewarpReason: String? = nil
    var bookReplacedByPageID: String? = nil
    var bookIsCurrent: Bool? = nil
    var bookPageNumberStatus: String? = nil
    var bookPageNumberLabel: String? = nil
    var bookPageNumberValue: Int? = nil
    var bookPageNumberKind: String? = nil
    var bookPageNumberConfidence: Double? = nil
    var bookPageNumberReason: String? = nil
    var bookPageNumberResultVersion: Int? = nil
    var bookExpectedPageLabel: String? = nil
    var bookContentFingerprint: String? = nil
    var bookFingerprintResultVersion: Int? = nil
    var bookAssemblyIncluded: Bool? = nil
    var bookAssemblyExclusionReason: String? = nil

    var showsExamSuggestion: Bool { examSuggestionVisible == true && examResultVersion != nil }
    var canRetakeBookSide: Bool {
        guard let bookSide, let bookSplitStatus else { return false }
        return ["left", "right"].contains(bookSide)
            && ["split", "retake"].contains(bookSplitStatus)
            && bookIsCurrent != false
            && activeResultVersion > 0
    }

    enum CodingKeys: String, CodingKey {
        case id
        case projectID = "project_id"
        case pageNumber = "page_number"
        case qualityWarning = "quality_warning"
        case rotationDegrees = "rotation_degrees"
        case activeResultVersion = "active_result_version"
        case reviewStatus = "review_status"
        case ocrStatus = "ocr_status"
        case examResultVersion = "exam_result_version"
        case examConfidenceBand = "exam_confidence_band"
        case examRecommendation = "exam_recommendation"
        case examSuggestionVisible = "exam_suggestion_visible"
        case bookCaptureID = "book_capture_id"
        case bookSide = "book_side"
        case bookSplitStatus = "book_split_status"
        case bookSplitConfidence = "book_split_confidence"
        case bookSplitReason = "book_split_reason"
        case bookDewarpApplied = "book_dewarp_applied"
        case bookDewarpSourceScore = "book_dewarp_source_score"
        case bookDewarpOutputScore = "book_dewarp_output_score"
        case bookDewarpReason = "book_dewarp_reason"
        case bookReplacedByPageID = "book_replaced_by_page_id"
        case bookIsCurrent = "book_is_current"
        case bookPageNumberStatus = "book_page_number_status"
        case bookPageNumberLabel = "book_page_number_label"
        case bookPageNumberValue = "book_page_number_value"
        case bookPageNumberKind = "book_page_number_kind"
        case bookPageNumberConfidence = "book_page_number_confidence"
        case bookPageNumberReason = "book_page_number_reason"
        case bookPageNumberResultVersion = "book_page_number_result_version"
        case bookExpectedPageLabel = "book_expected_page_label"
        case bookContentFingerprint = "book_content_fingerprint"
        case bookFingerprintResultVersion = "book_fingerprint_result_version"
        case bookAssemblyIncluded = "book_assembly_included"
        case bookAssemblyExclusionReason = "book_assembly_exclusion_reason"
    }
}

struct WorkspaceBookIntegrityIssue: Codable, Equatable, Sendable, Identifiable, Hashable {
    let key: String
    let kind: String
    let severity: String
    let messageCode: String
    let pageID: String?
    let relatedPageID: String?
    let printedPageLabel: String?
    let decision: String?
    let blocking: Bool

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, kind, severity, decision, blocking
        case messageCode = "message_code"
        case pageID = "page_id"
        case relatedPageID = "related_page_id"
        case printedPageLabel = "printed_page_label"
    }
}

struct WorkspaceBookIntegrityReport: Codable, Equatable, Sendable {
    let projectID: String
    let pagesChecked: Int
    let includedPageCount: Int
    let visiblePageNumberCount: Int
    let processingPageCount: Int
    let blockingIssueCount: Int
    let readyToAssemble: Bool
    let issues: [WorkspaceBookIntegrityIssue]

    enum CodingKeys: String, CodingKey {
        case issues
        case projectID = "project_id"
        case pagesChecked = "pages_checked"
        case includedPageCount = "included_page_count"
        case visiblePageNumberCount = "visible_page_number_count"
        case processingPageCount = "processing_page_count"
        case blockingIssueCount = "blocking_issue_count"
        case readyToAssemble = "ready_to_assemble"
    }
}

struct WorkspaceCorner: Codable, Equatable, Sendable {
    let x: Double
    let y: Double

    var valid: Bool { (0 ... 1).contains(x) && (0 ... 1).contains(y) }

    static let fullPage = [
        WorkspaceCorner(x: 0, y: 0),
        WorkspaceCorner(x: 1, y: 0),
        WorkspaceCorner(x: 1, y: 1),
        WorkspaceCorner(x: 0, y: 1),
    ]
}

enum WorkspaceFilter: String, CaseIterable, Codable, Sendable {
    case original
    case enhance
    case grayscale
    case bw
}

enum WorkspaceExportFormat: String, CaseIterable, Codable, Sendable {
    case pdf
    case jpg
}

enum WorkspaceExportQuality: String, CaseIterable, Codable, Sendable {
    case clear
    case balanced
    case small
}

struct WorkspaceExportArtifact: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: String
    let pageID: String?
    let sequence: Int
    let fileName: String
    let mimeType: String
    let sha256: String
    let sizeBytes: Int64

    enum CodingKeys: String, CodingKey {
        case id, sequence, sha256
        case pageID = "page_id"
        case fileName = "file_name"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
    }
}

struct WorkspaceExport: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let projectID: String
    let format: String
    let quality: String
    let includeOCRText: Bool
    let status: String
    let pageCount: Int
    let errorCode: String?
    let artifacts: [WorkspaceExportArtifact]
    let createdAt: String
    let completedAt: String?
    var bookAssemblySignature: String? = nil
    var bookAssemblyRevision: Int? = nil
    var bookPreviousExportID: String? = nil

    enum CodingKeys: String, CodingKey {
        case id, format, quality, status, artifacts
        case projectID = "project_id"
        case includeOCRText = "include_ocr_text"
        case pageCount = "page_count"
        case errorCode = "error_code"
        case createdAt = "created_at"
        case completedAt = "completed_at"
        case bookAssemblySignature = "book_assembly_signature"
        case bookAssemblyRevision = "book_assembly_revision"
        case bookPreviousExportID = "book_previous_export_id"
    }
}

struct DownloadedDocument: Equatable, Sendable, Identifiable {
    let id: String
    let url: URL
    let fileName: String
    let mimeType: String
}

struct RemoteDownload: Sendable {
    let temporaryURL: URL
    let suggestedFileName: String?
    let mimeType: String?
}

struct AccountDeletionReceipt: Codable, Equatable, Sendable {
    let id: String
    let status: String
    let requestedAt: String
    let executeAfter: String
    let canceledAt: String?
    let completedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case requestedAt = "requested_at"
        case executeAfter = "execute_after"
        case canceledAt = "canceled_at"
        case completedAt = "completed_at"
    }
}

struct AccountDeletionOutcome: Equatable, Sendable {
    let receipt: AccountDeletionReceipt
    let localCleanupSucceeded: Bool
}

enum WorkspaceError: Error, Equatable {
    case invalidPageOrder
    case invalidRotation
    case invalidExamResultVersion
    case invalidBookRetake
    case invalidBookSupplement
    case invalidBookIntegrityDecision
    case invalidCorners
    case invalidExport
    case invalidDownloadName
    case downloadOutsideUserDirectory
    case downloadSizeMismatch
    case downloadHashMismatch
    case localFileUnavailable
    case invalidAIConsent
    case invalidAIEnhancementKind
    case invalidAISourceVersion
    case invalidAIIdempotencyKey
    case invalidAIEnhancement
}
