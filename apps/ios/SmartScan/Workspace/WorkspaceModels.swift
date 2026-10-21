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

    enum CodingKeys: String, CodingKey {
        case id
        case projectID = "project_id"
        case pageNumber = "page_number"
        case qualityWarning = "quality_warning"
        case rotationDegrees = "rotation_degrees"
        case activeResultVersion = "active_result_version"
        case reviewStatus = "review_status"
        case ocrStatus = "ocr_status"
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

    enum CodingKeys: String, CodingKey {
        case id, format, quality, status, artifacts
        case projectID = "project_id"
        case includeOCRText = "include_ocr_text"
        case pageCount = "page_count"
        case errorCode = "error_code"
        case createdAt = "created_at"
        case completedAt = "completed_at"
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
    case invalidCorners
    case invalidExport
    case invalidDownloadName
    case downloadOutsideUserDirectory
    case downloadSizeMismatch
    case downloadHashMismatch
    case localFileUnavailable
}
