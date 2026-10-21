import Combine
import Foundation

enum WorkspacePresentation: Identifiable {
    case preview(DownloadedDocument)
    case share(DownloadedDocument)

    var id: String {
        switch self {
        case let .preview(document): return "preview-\(document.id)"
        case let .share(document): return "share-\(document.id)"
        }
    }
}

@MainActor
final class WorkspaceStore: ObservableObject {
    @Published private(set) var projects: [WorkspaceProject] = []
    @Published private(set) var selectedProject: WorkspaceProject?
    @Published private(set) var pages: [WorkspacePage] = []
    @Published private(set) var exports: [WorkspaceExport] = []
    @Published private(set) var previews: [String: DownloadedDocument] = [:]
    @Published private(set) var busy = false
    @Published private(set) var errorMessage: String?
    @Published var presentation: WorkspacePresentation?

    private let repository: WorkspaceServicing
    private let userID: String

    init(repository: WorkspaceServicing, userID: String) {
        self.repository = repository
        self.userID = userID
    }

    func loadProjects() async {
        await perform { self.projects = try await self.repository.projects(userID: self.userID) }
    }

    func open(_ project: WorkspaceProject) async {
        selectedProject = project
        pages = []
        exports = []
        previews = [:]
        await perform {
            async let pages = self.repository.pages(projectID: project.id)
            async let exports = self.repository.exports(projectID: project.id)
            let loadedPages = try await pages
            let loadedExports = try await exports
            self.pages = loadedPages.sorted(by: { $0.pageNumber < $1.pageNumber })
            self.exports = loadedExports
        }
    }

    func closeProject() {
        selectedProject = nil
        pages = []
        exports = []
        previews = [:]
        errorMessage = nil
    }

    func refreshProject() async {
        guard let selectedProject else { return }
        await open(selectedProject)
    }

    func move(pageID: String, delta: Int) async {
        guard let project = selectedProject,
              let index = pages.firstIndex(where: { $0.id == pageID }) else { return }
        let target = index + delta
        guard pages.indices.contains(target) else { return }
        var identifiers = pages.map(\.id)
        identifiers.swapAt(index, target)
        await perform {
            self.pages = try await self.repository.reorder(projectID: project.id, pageIDs: identifiers)
                .sorted(by: { $0.pageNumber < $1.pageNumber })
        }
    }

    func rotate(pageID: String) async {
        await updatePage { try await repository.rotate(pageID: pageID, degrees: 90) }
    }

    func edit(pageID: String, corners: [WorkspaceCorner], filter: WorkspaceFilter) async {
        await updatePage { try await repository.edit(pageID: pageID, corners: corners, filter: filter) }
    }

    func confirm(pageID: String) async {
        await updatePage { try await repository.review(pageID: pageID, confirmed: true) }
    }

    func dismissExamSuggestion(pageID: String, resultVersion: Int) async {
        await updatePage {
            try await repository.dismissExamSuggestion(pageID: pageID, resultVersion: resultVersion)
        }
    }

    func retakeBookSide(pageID: String, data: Data, mimeType: String) async -> WorkspacePage? {
        var outcome: WorkspacePage?
        await perform {
            let replacement = try await self.repository.retakeBookSide(
                pageID: pageID,
                data: data,
                mimeType: mimeType
            )
            guard let index = self.pages.firstIndex(where: { $0.id == pageID }) else { return }
            self.pages[index] = replacement
            self.pages.sort { $0.pageNumber < $1.pageNumber }
            self.previews[pageID] = nil
            self.previews[replacement.id] = nil
            outcome = replacement
        }
        return outcome
    }

    func loadPreview(for page: WorkspacePage) async {
        if previews[page.id]?.id == previewIdentifier(page) { return }
        await perform {
            let document = try await self.repository.downloadPreview(
                pageID: page.id,
                version: page.activeResultVersion,
                userID: self.userID
            )
            self.previews[page.id] = document
        }
    }

    func createExport(
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async {
        guard let project = selectedProject else { return }
        await perform {
            let created = try await self.repository.createExport(
                projectID: project.id,
                format: format,
                quality: quality,
                includeOCRText: includeOCRText
            )
            self.exports.removeAll { $0.id == created.id }
            self.exports.insert(created, at: 0)
        }
    }

    func refresh(exportID: String) async {
        await perform {
            let refreshed = try await self.repository.refreshExport(id: exportID)
            if let index = self.exports.firstIndex(where: { $0.id == exportID }) {
                self.exports[index] = refreshed
            } else {
                self.exports.insert(refreshed, at: 0)
            }
        }
    }

    func present(_ artifact: WorkspaceExportArtifact, sharing: Bool) async {
        await perform {
            let document = try await self.repository.downloadArtifact(artifact, userID: self.userID)
            self.presentation = sharing ? .share(document) : .preview(document)
        }
    }

    func clearError() { errorMessage = nil }

    private func updatePage(_ operation: () async throws -> WorkspacePage) async {
        await perform {
            let updated = try await operation()
            if let index = self.pages.firstIndex(where: { $0.id == updated.id }) {
                self.pages[index] = updated
                self.pages.sort { $0.pageNumber < $1.pageNumber }
            }
            self.previews[updated.id] = nil
        }
    }

    private func perform(_ operation: () async throws -> Void) async {
        busy = true
        errorMessage = nil
        defer { busy = false }
        do {
            try await operation()
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func message(for error: Error) -> String {
        if let apiError = error as? APIClientError {
            switch apiError {
            case let .http(statusCode, _):
                if statusCode == 404 { return String(localized: "This item is no longer available.") }
                if statusCode == 401 { return String(localized: "Your session has expired. Please log in again.") }
            default: break
            }
        }
        if let workspaceError = error as? WorkspaceError,
           workspaceError == .downloadHashMismatch || workspaceError == .downloadSizeMismatch {
            return String(localized: "The downloaded file failed integrity verification.")
        }
        return String(localized: "The action could not be completed. Try again.")
    }

    private func previewIdentifier(_ page: WorkspacePage) -> String {
        "page-\(page.id)-v\(page.activeResultVersion)"
    }
}
