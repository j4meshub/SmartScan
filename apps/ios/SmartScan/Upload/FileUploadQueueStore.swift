import Foundation

actor FileUploadQueueStore {
    private let queueRoot: URL
    private let captureRoot: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder = JSONDecoder()

    init(root: URL? = nil, captureRoot: URL? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        let support = UserStoragePaths.applicationSupportRoot(fileManager: fileManager)
        queueRoot = root ?? support.appendingPathComponent("upload-queue", isDirectory: true)
        self.captureRoot = captureRoot ?? support.appendingPathComponent("captures", isDirectory: true)
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
    }

    func enqueue(
        record: CaptureRecord,
        ownerUserID: String,
        localProjectID: String,
        title: String,
        mode: ScanModeKind,
        now: String = ISO8601DateFormatter().string(from: Date())
    ) throws {
        guard !ownerUserID.isEmpty else { throw UploadQueueStoreError.invalidOwner }
        let userCaptureRoot = captureRoot.appendingPathComponent(UserStoragePaths.digest(for: ownerUserID), isDirectory: true)
        guard UserStoragePaths.isDescendant(record.originalURL, of: userCaptureRoot),
              UserStoragePaths.isDescendant(record.evidenceURL, of: userCaptureRoot) else {
            throw UploadQueueStoreError.captureOutsideUserDirectory
        }
        guard fileManager.fileExists(atPath: record.originalURL.path),
              fileManager.fileExists(atPath: record.evidenceURL.path),
              let attributes = try? fileManager.attributesOfItem(atPath: record.originalURL.path),
              let size = (attributes[.size] as? NSNumber)?.int64Value,
              size > 15 else {
            throw UploadQueueStoreError.captureMissing
        }

        var envelope = try load(ownerUserID: ownerUserID)
        if envelope.projects.flatMap(\.uploads).contains(where: { $0.captureID == record.id }) { return }
        let upload = QueuedUpload(
            id: UUID().uuidString.lowercased(),
            captureID: record.id,
            originalURL: record.originalURL,
            evidenceURL: record.evidenceURL,
            fileName: record.originalURL.lastPathComponent,
            mimeType: "image/jpeg",
            sizeBytes: size,
            sha256: nil,
            idempotencyKey: newIdempotencyKey(),
            serverUploadID: nil,
            uploadedBytes: 0,
            status: .queued,
            pageID: nil,
            errorCode: nil,
            createdAt: now
        )
        if let index = envelope.projects.firstIndex(where: { $0.id == localProjectID }) {
            guard envelope.projects[index].ownerUserID == ownerUserID,
                  envelope.projects[index].mode == mode else {
                throw UploadQueueStoreError.projectConflict
            }
            envelope.projects[index].uploads.append(upload)
        } else {
            envelope.projects.append(
                LocalUploadProject(
                    id: localProjectID,
                    ownerUserID: ownerUserID,
                    title: title,
                    mode: mode,
                    serverProjectID: nil,
                    uploads: [upload]
                )
            )
        }
        try save(envelope, ownerUserID: ownerUserID)
    }

    func nextPending(ownerUserID: String) throws -> (LocalUploadProject, QueuedUpload)? {
        let envelope = try load(ownerUserID: ownerUserID)
        for project in envelope.projects {
            if let upload = project.uploads.first(where: { $0.status.pending }) {
                return (project, upload)
            }
        }
        return nil
    }

    func snapshot(ownerUserID: String) throws -> UploadQueueEnvelope {
        try load(ownerUserID: ownerUserID)
    }

    func pendingCount(ownerUserID: String) throws -> Int {
        try load(ownerUserID: ownerUserID).projects.flatMap(\.uploads).filter { $0.status.pending }.count
    }

    func setServerProjectID(ownerUserID: String, localProjectID: String, serverProjectID: String) throws {
        try mutateProject(ownerUserID: ownerUserID, localProjectID: localProjectID) { project in
            project.serverProjectID = serverProjectID
        }
    }

    func setUploadSession(
        ownerUserID: String,
        localProjectID: String,
        uploadID: String,
        serverUploadID: String,
        sha256: String,
        uploadedBytes: Int64
    ) throws {
        try mutateUpload(ownerUserID: ownerUserID, localProjectID: localProjectID, uploadID: uploadID) { upload in
            upload.serverUploadID = serverUploadID
            upload.sha256 = sha256
            upload.uploadedBytes = uploadedBytes
            upload.status = .uploading
            upload.errorCode = nil
        }
    }

    func updateProgress(ownerUserID: String, localProjectID: String, uploadID: String, uploadedBytes: Int64) throws {
        try mutateUpload(ownerUserID: ownerUserID, localProjectID: localProjectID, uploadID: uploadID) { upload in
            upload.uploadedBytes = uploadedBytes
            upload.status = .uploading
        }
    }

    func mark(
        ownerUserID: String,
        localProjectID: String,
        uploadID: String,
        status: UploadQueueStatus,
        errorCode: String?
    ) throws {
        try mutateUpload(ownerUserID: ownerUserID, localProjectID: localProjectID, uploadID: uploadID) { upload in
            upload.status = status
            upload.errorCode = errorCode
        }
    }

    func markCompleted(ownerUserID: String, localProjectID: String, uploadID: String, pageID: String) throws {
        try mutateUpload(ownerUserID: ownerUserID, localProjectID: localProjectID, uploadID: uploadID) { upload in
            upload.status = .completed
            upload.pageID = pageID
            upload.errorCode = nil
            upload.uploadedBytes = upload.sizeBytes
        }
    }

    func rotateUploadSession(ownerUserID: String, localProjectID: String, uploadID: String) throws {
        try mutateUpload(ownerUserID: ownerUserID, localProjectID: localProjectID, uploadID: uploadID) { upload in
            upload.idempotencyKey = newIdempotencyKey()
            upload.serverUploadID = nil
            upload.uploadedBytes = 0
            upload.status = .retrying
            upload.errorCode = "upload_session_expired"
        }
    }

    private func mutateProject(
        ownerUserID: String,
        localProjectID: String,
        mutation: (inout LocalUploadProject) throws -> Void
    ) throws {
        var envelope = try load(ownerUserID: ownerUserID)
        guard let projectIndex = envelope.projects.firstIndex(where: { $0.id == localProjectID }) else {
            throw UploadQueueStoreError.projectConflict
        }
        try mutation(&envelope.projects[projectIndex])
        try save(envelope, ownerUserID: ownerUserID)
    }

    private func mutateUpload(
        ownerUserID: String,
        localProjectID: String,
        uploadID: String,
        mutation: (inout QueuedUpload) -> Void
    ) throws {
        try mutateProject(ownerUserID: ownerUserID, localProjectID: localProjectID) { project in
            guard let uploadIndex = project.uploads.firstIndex(where: { $0.id == uploadID }) else {
                throw UploadQueueStoreError.uploadMissing
            }
            mutation(&project.uploads[uploadIndex])
        }
    }

    private func load(ownerUserID: String) throws -> UploadQueueEnvelope {
        let file = queueFile(ownerUserID: ownerUserID)
        guard fileManager.fileExists(atPath: file.path) else { return .empty }
        let envelope = try decoder.decode(UploadQueueEnvelope.self, from: Data(contentsOf: file))
        guard envelope.version == 1,
              envelope.projects.allSatisfy({ $0.ownerUserID == ownerUserID }) else {
            throw UploadQueueStoreError.invalidQueueVersion
        }
        return envelope
    }

    private func save(_ envelope: UploadQueueEnvelope, ownerUserID: String) throws {
        let file = queueFile(ownerUserID: ownerUserID)
        try fileManager.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try encoder.encode(envelope).write(
            to: file,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func queueFile(ownerUserID: String) -> URL {
        queueRoot.appendingPathComponent(UserStoragePaths.digest(for: ownerUserID), isDirectory: true)
            .appendingPathComponent("queue.json")
    }
}

private func newIdempotencyKey() -> String {
    UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
}
