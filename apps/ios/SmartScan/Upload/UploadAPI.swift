import Foundation

protocol SmartScanUploadAPI {
    func createProject(title: String, mode: ScanModeKind) async throws -> RemoteProject
    func createUpload(_ request: RemoteUploadCreate) async throws -> RemoteUpload
    func getUpload(id: String) async throws -> RemoteUpload
    func putChunk(uploadID: String, index: Int, sha256: String, data: Data) async throws -> RemoteChunkReceipt
    func completeUpload(id: String) async throws -> RemotePage
}

struct RemoteProject: Decodable, Equatable, Sendable {
    let id: String
}

struct RemoteUploadCreate: Encodable, Equatable, Sendable {
    let projectID: String
    let fileName: String
    let mimeType: String
    let sizeBytes: Int64
    let sha256: String
    let idempotencyKey: String

    enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case fileName = "file_name"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
        case sha256
        case idempotencyKey = "idempotency_key"
    }
}

struct RemoteUpload: Decodable, Equatable, Sendable {
    let id: String
    let projectID: String
    let fileName: String
    let mimeType: String
    let sizeBytes: Int64
    let chunkSize: Int64
    let totalChunks: Int
    let receivedChunks: [Int]
    let status: String
    let pageID: String?
    let expiresAt: String

    enum CodingKeys: String, CodingKey {
        case id, status
        case projectID = "project_id"
        case fileName = "file_name"
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
        case chunkSize = "chunk_size"
        case totalChunks = "total_chunks"
        case receivedChunks = "received_chunks"
        case pageID = "page_id"
        case expiresAt = "expires_at"
    }
}

struct RemoteChunkReceipt: Decodable, Equatable, Sendable {
    let uploadID: String
    let chunkIndex: Int
    let sizeBytes: Int64
    let sha256: String

    enum CodingKeys: String, CodingKey {
        case uploadID = "upload_id"
        case chunkIndex = "chunk_index"
        case sizeBytes = "size_bytes"
        case sha256
    }
}

struct RemotePage: Decodable, Equatable, Sendable {
    let id: String
}

extension URLSessionSmartScanAPI: SmartScanUploadAPI {
    func createProject(title: String, mode: ScanModeKind) async throws -> RemoteProject {
        var request = try makeRequest(path: "v1/projects", method: "POST", authenticated: true)
        request.httpBody = try JSONEncoder().encode(
            ProjectCreateRequest(title: title, mode: mode.rawValue, readingOrder: "ltr")
        )
        return try await execute(request)
    }

    func createUpload(_ payload: RemoteUploadCreate) async throws -> RemoteUpload {
        var request = try makeRequest(path: "v1/uploads", method: "POST", authenticated: true)
        request.httpBody = try JSONEncoder().encode(payload)
        return try await execute(request)
    }

    func getUpload(id: String) async throws -> RemoteUpload {
        try await execute(makeRequest(path: "v1/uploads/\(id)", method: "GET", authenticated: true))
    }

    func putChunk(uploadID: String, index: Int, sha256: String, data: Data) async throws -> RemoteChunkReceipt {
        var request = try makeRequest(
            path: "v1/uploads/\(uploadID)/chunks/\(index)",
            method: "PUT",
            authenticated: true
        )
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(sha256, forHTTPHeaderField: "X-Chunk-Sha256")
        request.httpBody = data
        return try await execute(request)
    }

    func completeUpload(id: String) async throws -> RemotePage {
        try await execute(
            makeRequest(path: "v1/uploads/\(id)/complete", method: "POST", authenticated: true)
        )
    }
}

private struct ProjectCreateRequest: Encodable {
    let title: String
    let mode: String
    let readingOrder: String

    enum CodingKeys: String, CodingKey {
        case title, mode
        case readingOrder = "reading_order"
    }
}
