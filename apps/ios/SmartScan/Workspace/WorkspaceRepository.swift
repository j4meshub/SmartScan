import CryptoKit
import Foundation

protocol WorkspaceServicing {
    func projects(userID: String) async throws -> [WorkspaceProject]
    func pages(projectID: String) async throws -> [WorkspacePage]
    func exports(projectID: String) async throws -> [WorkspaceExport]
    func reorder(projectID: String, pageIDs: [String]) async throws -> [WorkspacePage]
    func rotate(pageID: String, degrees: Int) async throws -> WorkspacePage
    func edit(pageID: String, corners: [WorkspaceCorner], filter: WorkspaceFilter) async throws -> WorkspacePage
    func review(pageID: String, confirmed: Bool) async throws -> WorkspacePage
    func dismissExamSuggestion(pageID: String, resultVersion: Int) async throws -> WorkspacePage
    func retakeBookSide(pageID: String, data: Data, mimeType: String) async throws -> WorkspacePage
    func bookIntegrity(projectID: String) async throws -> WorkspaceBookIntegrityReport
    func decideBookIntegrity(projectID: String, issueKey: String, decision: String) async throws -> WorkspaceBookIntegrityReport
    func supplementBookPage(
        projectID: String,
        data: Data,
        mimeType: String,
        insertAt: Int,
        expectedPageLabel: String
    ) async throws -> WorkspacePage
    func assembleBook(
        projectID: String,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport
    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport
    func refreshExport(id: String) async throws -> WorkspaceExport
    func downloadPreview(pageID: String, version: Int, userID: String) async throws -> DownloadedDocument
    func downloadArtifact(_ artifact: WorkspaceExportArtifact, userID: String) async throws -> DownloadedDocument
}

actor WorkspaceRepository: WorkspaceServicing {
    private let api: SmartScanWorkspaceAPI
    private let authentication: AuthenticationRepository
    private let cache: UserScopedProjectCaching
    private let root: URL
    private let fileManager: FileManager

    init(
        api: SmartScanWorkspaceAPI,
        authentication: AuthenticationRepository,
        cache: UserScopedProjectCaching,
        root: URL? = nil,
        fileManager: FileManager = .default
    ) {
        self.api = api
        self.authentication = authentication
        self.cache = cache
        self.fileManager = fileManager
        self.root = root ?? UserStoragePaths.applicationSupportRoot(fileManager: fileManager)
            .appendingPathComponent("downloads", isDirectory: true)
    }

    func projects(userID: String) async throws -> [WorkspaceProject] {
        do {
            let remote = try await withSingleRefresh { try await api.listProjects() }
            try await cache.replaceProjects(remote.map(\.cached), for: userID)
            return remote
        } catch {
            let local = try await cache.projects(for: userID)
            guard !local.isEmpty else { throw error }
            return local.map(WorkspaceProject.init(cached:))
        }
    }

    func pages(projectID: String) async throws -> [WorkspacePage] {
        try await withSingleRefresh { try await api.listPages(projectID: projectID) }
    }

    func exports(projectID: String) async throws -> [WorkspaceExport] {
        try await withSingleRefresh { try await api.listExports(projectID: projectID) }
    }

    func reorder(projectID: String, pageIDs: [String]) async throws -> [WorkspacePage] {
        guard !pageIDs.isEmpty, Set(pageIDs).count == pageIDs.count else {
            throw WorkspaceError.invalidPageOrder
        }
        return try await withSingleRefresh {
            try await api.reorderPages(projectID: projectID, pageIDs: pageIDs)
        }
    }

    func rotate(pageID: String, degrees: Int) async throws -> WorkspacePage {
        guard [90, 180, 270].contains(degrees) else { throw WorkspaceError.invalidRotation }
        return try await withSingleRefresh { try await api.rotatePage(id: pageID, degrees: degrees) }
    }

    func edit(
        pageID: String,
        corners: [WorkspaceCorner],
        filter: WorkspaceFilter
    ) async throws -> WorkspacePage {
        guard corners.count == 4, corners.allSatisfy(\.valid) else { throw WorkspaceError.invalidCorners }
        return try await withSingleRefresh {
            try await api.editPage(id: pageID, corners: corners, filter: filter)
        }
    }

    func review(pageID: String, confirmed: Bool) async throws -> WorkspacePage {
        try await withSingleRefresh { try await api.reviewPage(id: pageID, confirmed: confirmed) }
    }

    func dismissExamSuggestion(pageID: String, resultVersion: Int) async throws -> WorkspacePage {
        guard resultVersion > 0 else { throw WorkspaceError.invalidExamResultVersion }
        return try await withSingleRefresh {
            try await api.dismissExamSuggestion(id: pageID, resultVersion: resultVersion)
        }
    }

    func retakeBookSide(pageID: String, data: Data, mimeType: String) async throws -> WorkspacePage {
        guard !data.isEmpty, ["image/jpeg", "image/png", "image/webp"].contains(mimeType) else {
            throw WorkspaceError.invalidBookRetake
        }
        return try await withSingleRefresh {
            try await api.retakeBookSide(id: pageID, data: data, mimeType: mimeType)
        }
    }

    func bookIntegrity(projectID: String) async throws -> WorkspaceBookIntegrityReport {
        try await withSingleRefresh { try await api.bookIntegrity(projectID: projectID) }
    }

    func decideBookIntegrity(
        projectID: String,
        issueKey: String,
        decision: String
    ) async throws -> WorkspaceBookIntegrityReport {
        let allowed = ["ignored", "confirmed_absent", "keep_both", "exclude_duplicate", "reopen"]
        guard !issueKey.isEmpty, allowed.contains(decision) else {
            throw WorkspaceError.invalidBookIntegrityDecision
        }
        return try await withSingleRefresh {
            try await api.decideBookIntegrity(projectID: projectID, issueKey: issueKey, decision: decision)
        }
    }

    func supplementBookPage(
        projectID: String,
        data: Data,
        mimeType: String,
        insertAt: Int,
        expectedPageLabel: String
    ) async throws -> WorkspacePage {
        guard !data.isEmpty,
              ["image/jpeg", "image/png", "image/webp"].contains(mimeType),
              insertAt > 0,
              !expectedPageLabel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw WorkspaceError.invalidBookSupplement
        }
        return try await withSingleRefresh {
            try await api.supplementBookPage(
                projectID: projectID,
                data: data,
                mimeType: mimeType,
                insertAt: insertAt,
                expectedPageLabel: expectedPageLabel
            )
        }
    }

    func assembleBook(
        projectID: String,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        try await withSingleRefresh {
            try await api.assembleBook(
                projectID: projectID,
                quality: quality,
                includeOCRText: includeOCRText
            )
        }
    }

    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        try await withSingleRefresh {
            try await api.createExport(
                projectID: projectID,
                format: format,
                quality: quality,
                includeOCRText: includeOCRText && format == .pdf
            )
        }
    }

    func refreshExport(id: String) async throws -> WorkspaceExport {
        try await withSingleRefresh { try await api.getExport(id: id) }
    }

    func downloadPreview(pageID: String, version: Int, userID: String) async throws -> DownloadedDocument {
        let download = try await withSingleRefresh { try await api.downloadPage(id: pageID) }
        let fileExtension = extensionFor(mimeType: download.mimeType) ?? "img"
        let name = "page-\(stableDigest(pageID).prefix(16))-v\(version).\(fileExtension)"
        return try persist(
            download,
            userID: userID,
            category: "previews",
            identifier: "page-\(pageID)-v\(version)",
            requestedName: name,
            displayName: name,
            expectedSize: nil,
            expectedSHA256: nil,
            fallbackMimeType: download.mimeType ?? "application/octet-stream"
        )
    }

    func downloadArtifact(
        _ artifact: WorkspaceExportArtifact,
        userID: String
    ) async throws -> DownloadedDocument {
        let download = try await withSingleRefresh { try await api.downloadArtifact(id: artifact.id) }
        return try persist(
            download,
            userID: userID,
            category: "exports",
            identifier: "artifact-\(artifact.id)",
            requestedName: "\(artifact.id.prefix(12))-\(artifact.fileName)",
            displayName: artifact.fileName,
            expectedSize: artifact.sizeBytes,
            expectedSHA256: artifact.sha256,
            fallbackMimeType: artifact.mimeType
        )
    }

    private func withSingleRefresh<T>(_ operation: () async throws -> T) async throws -> T {
        do {
            return try await operation()
        } catch let error as APIClientError {
            guard case .http(statusCode: 401, detail: _) = error else { throw error }
            _ = try await authentication.refresh()
            return try await operation()
        }
    }

    private func persist(
        _ download: RemoteDownload,
        userID: String,
        category: String,
        identifier: String,
        requestedName: String,
        displayName: String,
        expectedSize: Int64?,
        expectedSHA256: String?,
        fallbackMimeType: String
    ) throws -> DownloadedDocument {
        defer { try? fileManager.removeItem(at: download.temporaryURL) }
        guard !userID.isEmpty else { throw WorkspaceError.downloadOutsideUserDirectory }
        let safeName = URL(fileURLWithPath: requestedName).lastPathComponent.trimmingCharacters(in: .whitespaces)
        let safeDisplayName = URL(fileURLWithPath: displayName).lastPathComponent.trimmingCharacters(in: .whitespaces)
        guard !safeName.isEmpty, !safeDisplayName.isEmpty,
              ![".", ".."].contains(safeName), ![".", ".."].contains(safeDisplayName) else {
            throw WorkspaceError.invalidDownloadName
        }
        let userRoot = root.appendingPathComponent(UserStoragePaths.digest(for: userID), isDirectory: true)
        let directory = userRoot.appendingPathComponent(category, isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let destination = directory.appendingPathComponent(safeName)
        guard UserStoragePaths.isDescendant(destination, of: userRoot) else {
            throw WorkspaceError.downloadOutsideUserDirectory
        }
        let partial = directory.appendingPathComponent(".\(UUID().uuidString).part")
        var hasher = SHA256()
        var written = Int64(0)
        do {
            guard fileManager.createFile(atPath: partial.path, contents: nil) else {
                throw WorkspaceError.localFileUnavailable
            }
            let input = try FileHandle(forReadingFrom: download.temporaryURL)
            let output = try FileHandle(forWritingTo: partial)
            defer {
                try? input.close()
                try? output.close()
            }
            while true {
                let data = try input.read(upToCount: 1024 * 1024) ?? Data()
                if data.isEmpty { break }
                hasher.update(data: data)
                try output.write(contentsOf: data)
                written += Int64(data.count)
            }
            try output.synchronize()
            try output.close()
            try input.close()
            if let expectedSize, written != expectedSize { throw WorkspaceError.downloadSizeMismatch }
            let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
            if let expectedSHA256, digest != expectedSHA256.lowercased() {
                throw WorkspaceError.downloadHashMismatch
            }
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: partial.path
            )
            if fileManager.fileExists(atPath: destination.path) {
                _ = try fileManager.replaceItemAt(destination, withItemAt: partial)
            } else {
                try fileManager.moveItem(at: partial, to: destination)
            }
            return DownloadedDocument(
                id: identifier,
                url: destination,
                fileName: safeDisplayName,
                mimeType: download.mimeType ?? fallbackMimeType
            )
        } catch {
            try? fileManager.removeItem(at: partial)
            throw error
        }
    }
}

private extension WorkspaceProject {
    var cached: CachedProject {
        CachedProject(id: id, title: displayName, mode: mode, updatedAt: updatedAt)
    }

    init(cached: CachedProject) {
        self.init(
            id: cached.id,
            title: cached.title,
            suggestedName: nil,
            mode: cached.mode,
            readingOrder: "ltr",
            createdAt: cached.updatedAt,
            updatedAt: cached.updatedAt
        )
    }
}

private func stableDigest(_ value: String) -> String {
    SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
}

private func extensionFor(mimeType: String?) -> String? {
    switch mimeType?.lowercased() {
    case "image/jpeg": return "jpg"
    case "image/png": return "png"
    case "image/webp": return "webp"
    case "application/pdf": return "pdf"
    default: return nil
    }
}
