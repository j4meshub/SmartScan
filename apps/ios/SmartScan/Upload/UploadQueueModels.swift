import Foundation

enum UploadQueueStatus: String, Codable, Equatable, Sendable {
    case queued
    case uploading
    case retrying
    case waitingForLogin = "waiting_for_login"
    case completed
    case failed

    var pending: Bool {
        switch self {
        case .queued, .uploading, .retrying, .waitingForLogin: true
        case .completed, .failed: false
        }
    }
}

struct LocalUploadProject: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let ownerUserID: String
    let title: String
    let mode: ScanModeKind
    var serverProjectID: String?
    var uploads: [QueuedUpload]
}

struct QueuedUpload: Codable, Equatable, Sendable, Identifiable {
    let id: String
    let captureID: String
    let originalURL: URL
    let evidenceURL: URL
    let fileName: String
    let mimeType: String
    let sizeBytes: Int64
    var sha256: String?
    var idempotencyKey: String
    var serverUploadID: String?
    var uploadedBytes: Int64
    var status: UploadQueueStatus
    var pageID: String?
    var errorCode: String?
    let createdAt: String
}

struct UploadQueueEnvelope: Codable, Equatable, Sendable {
    let version: Int
    var projects: [LocalUploadProject]

    static let empty = UploadQueueEnvelope(version: 1, projects: [])
}

enum UploadQueueStoreError: Error, Equatable {
    case invalidOwner
    case captureOutsideUserDirectory
    case captureMissing
    case invalidQueueVersion
    case projectConflict
    case uploadMissing
}
