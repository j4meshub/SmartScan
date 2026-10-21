import Foundation

struct WorkspaceProject: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: String
    let title: String
    let suggestedName: String?
    let mode: String
    let readingOrder: String
    let createdAt: String
    let updatedAt: String

    var displayName: String { suggestedName ?? title }

    enum CodingKeys: String, CodingKey {
        case id, title, mode
        case suggestedName = "suggested_name"
        case readingOrder = "reading_order"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
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
}
