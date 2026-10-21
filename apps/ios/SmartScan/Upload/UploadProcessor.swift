import CryptoKit
import Foundation

enum UploadProcessResult: Equatable, Sendable {
    case completed
    case empty
    case retry
    case waitingForLogin
    case failed
}

actor UploadProcessor {
    private let api: SmartScanUploadAPI
    private let queue: FileUploadQueueStore
    private let sessions: SessionStoring
    private let authentication: AuthenticationRepository

    init(
        api: SmartScanUploadAPI,
        queue: FileUploadQueueStore,
        sessions: SessionStoring,
        authentication: AuthenticationRepository
    ) {
        self.api = api
        self.queue = queue
        self.sessions = sessions
        self.authentication = authentication
    }

    func processNext(ownerUserID: String) async -> UploadProcessResult {
        guard sessions.current()?.userID == ownerUserID else {
            await markNextWaiting(ownerUserID: ownerUserID)
            return .waitingForLogin
        }
        do {
            return try await processWithSingleRefresh(ownerUserID: ownerUserID)
        } catch is CancellationError {
            await markNextRetrying(ownerUserID: ownerUserID, code: "background_expired")
            return .retry
        } catch {
            return await classify(error, ownerUserID: ownerUserID)
        }
    }

    private func processWithSingleRefresh(ownerUserID: String) async throws -> UploadProcessResult {
        do {
            return try await process(ownerUserID: ownerUserID)
        } catch let error as APIClientError {
            guard case .http(statusCode: 401, detail: _) = error else { throw error }
            do {
                _ = try await authentication.refresh()
                return try await process(ownerUserID: ownerUserID)
            } catch {
                await markNextWaiting(ownerUserID: ownerUserID)
                return .waitingForLogin
            }
        }
    }

    private func process(ownerUserID: String) async throws -> UploadProcessResult {
        try Task.checkCancellation()
        guard let next = try await queue.nextPending(ownerUserID: ownerUserID) else { return .empty }
        var project = next.0
        let upload = next.1
        guard FileManager.default.fileExists(atPath: upload.originalURL.path),
              let attributes = try? FileManager.default.attributesOfItem(atPath: upload.originalURL.path),
              (attributes[.size] as? NSNumber)?.int64Value == upload.sizeBytes else {
            try await queue.mark(
                ownerUserID: ownerUserID,
                localProjectID: project.id,
                uploadID: upload.id,
                status: .failed,
                errorCode: "local_file_missing"
            )
            return .failed
        }

        if project.serverProjectID == nil {
            let remote = try await api.createProject(title: project.title, mode: project.mode)
            try await queue.setServerProjectID(
                ownerUserID: ownerUserID,
                localProjectID: project.id,
                serverProjectID: remote.id
            )
            project.serverProjectID = remote.id
        }
        let fileHash = try upload.sha256 ?? sha256(file: upload.originalURL)
        let remote: RemoteUpload
        if let serverUploadID = upload.serverUploadID {
            do {
                remote = try await api.getUpload(id: serverUploadID)
            } catch let error as APIClientError {
                if case .http(statusCode: 410, detail: _) = error {
                    try await queue.rotateUploadSession(
                        ownerUserID: ownerUserID,
                        localProjectID: project.id,
                        uploadID: upload.id
                    )
                    return .retry
                }
                throw error
            }
        } else {
            remote = try await api.createUpload(
                RemoteUploadCreate(
                    projectID: project.serverProjectID!,
                    fileName: upload.fileName,
                    mimeType: upload.mimeType,
                    sizeBytes: upload.sizeBytes,
                    sha256: fileHash,
                    idempotencyKey: upload.idempotencyKey
                )
            )
        }
        if remote.status == "expired" {
            try await queue.rotateUploadSession(
                ownerUserID: ownerUserID,
                localProjectID: project.id,
                uploadID: upload.id
            )
            return .retry
        }
        if remote.status == "completed", let pageID = remote.pageID {
            try await queue.markCompleted(
                ownerUserID: ownerUserID,
                localProjectID: project.id,
                uploadID: upload.id,
                pageID: pageID
            )
            return .completed
        }
        try validate(remote: remote, local: upload)
        let received = Set(remote.receivedChunks)
        var uploadedBytes = try received.reduce(Int64(0)) { total, index in
            total + (try chunkLength(index: index, chunkSize: remote.chunkSize, totalSize: upload.sizeBytes))
        }
        try await queue.setUploadSession(
            ownerUserID: ownerUserID,
            localProjectID: project.id,
            uploadID: upload.id,
            serverUploadID: remote.id,
            sha256: fileHash,
            uploadedBytes: uploadedBytes
        )
        let handle = try FileHandle(forReadingFrom: upload.originalURL)
        defer { try? handle.close() }
        for index in 0 ..< remote.totalChunks where !received.contains(index) {
            try Task.checkCancellation()
            let data = try readChunk(
                handle: handle,
                index: index,
                chunkSize: remote.chunkSize,
                totalSize: upload.sizeBytes
            )
            let digest = sha256(data: data)
            let receipt = try await api.putChunk(uploadID: remote.id, index: index, sha256: digest, data: data)
            guard receipt.uploadID == remote.id,
                  receipt.chunkIndex == index,
                  receipt.sizeBytes == Int64(data.count),
                  receipt.sha256 == digest else {
                throw UploadProcessorError.invalidChunkReceipt
            }
            uploadedBytes += Int64(data.count)
            try await queue.updateProgress(
                ownerUserID: ownerUserID,
                localProjectID: project.id,
                uploadID: upload.id,
                uploadedBytes: uploadedBytes
            )
        }
        let page = try await api.completeUpload(id: remote.id)
        try await queue.markCompleted(
            ownerUserID: ownerUserID,
            localProjectID: project.id,
            uploadID: upload.id,
            pageID: page.id
        )
        return .completed
    }

    private func classify(_ error: Error, ownerUserID: String) async -> UploadProcessResult {
        if let apiError = error as? APIClientError {
            switch apiError {
            case let .http(statusCode, _):
                if statusCode == 401 {
                    await markNextWaiting(ownerUserID: ownerUserID)
                    return .waitingForLogin
                }
                if statusCode == 408 || statusCode == 429 || statusCode >= 500 {
                    await markNextRetrying(ownerUserID: ownerUserID, code: "transient_failure")
                    return .retry
                }
            default: break
            }
        }
        if error is URLError {
            await markNextRetrying(ownerUserID: ownerUserID, code: "transient_failure")
            return .retry
        }
        await markNextFailed(ownerUserID: ownerUserID)
        return .failed
    }

    private func markNextWaiting(ownerUserID: String) async {
        await markNext(ownerUserID: ownerUserID, status: .waitingForLogin, code: "login_required")
    }

    private func markNextRetrying(ownerUserID: String, code: String) async {
        await markNext(ownerUserID: ownerUserID, status: .retrying, code: code)
    }

    private func markNextFailed(ownerUserID: String) async {
        await markNext(ownerUserID: ownerUserID, status: .failed, code: "upload_failed")
    }

    private func markNext(ownerUserID: String, status: UploadQueueStatus, code: String) async {
        guard let next = try? await queue.nextPending(ownerUserID: ownerUserID) else { return }
        try? await queue.mark(
            ownerUserID: ownerUserID,
            localProjectID: next.0.id,
            uploadID: next.1.id,
            status: status,
            errorCode: code
        )
    }

    private func validate(remote: RemoteUpload, local: QueuedUpload) throws {
        guard remote.sizeBytes == local.sizeBytes,
              remote.chunkSize > 0,
              remote.totalChunks > 0,
              Int64(remote.totalChunks) == (local.sizeBytes + remote.chunkSize - 1) / remote.chunkSize,
              remote.receivedChunks.allSatisfy({ $0 >= 0 && $0 < remote.totalChunks }) else {
            throw UploadProcessorError.invalidChunkPlan
        }
    }
}

enum UploadProcessorError: Error, Equatable {
    case invalidChunkPlan
    case invalidChunkReceipt
    case invalidChunkIndex
}

private func chunkLength(index: Int, chunkSize: Int64, totalSize: Int64) throws -> Int64 {
    let length = min(chunkSize, totalSize - Int64(index) * chunkSize)
    guard length > 0 else { throw UploadProcessorError.invalidChunkIndex }
    return length
}

private func readChunk(handle: FileHandle, index: Int, chunkSize: Int64, totalSize: Int64) throws -> Data {
    let length = try chunkLength(index: index, chunkSize: chunkSize, totalSize: totalSize)
    guard length <= Int64(Int.max) else { throw UploadProcessorError.invalidChunkPlan }
    try handle.seek(toOffset: UInt64(index) * UInt64(chunkSize))
    let data = try handle.read(upToCount: Int(length)) ?? Data()
    guard Int64(data.count) == length else { throw UploadProcessorError.invalidChunkPlan }
    return data
}

private func sha256(file: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: file)
    defer { try? handle.close() }
    var hasher = SHA256()
    while true {
        let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
        if data.isEmpty { break }
        hasher.update(data: data)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

private func sha256(data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}
