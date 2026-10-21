@testable import SmartScan
import CryptoKit
import Foundation
import XCTest

final class WorkspaceRepositoryTests: XCTestCase {
    func testInvalidPageOrderAndCornersAreRejectedBeforeNetwork() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let api = FakeWorkspaceAPI()
        let repository = fixture.repository(api: api)

        do {
            _ = try await repository.reorder(projectID: "project-1", pageIDs: ["page-1", "page-1"])
            XCTFail("重复页面必须被拒绝")
        } catch {
            XCTAssertEqual(error as? WorkspaceError, .invalidPageOrder)
        }
        do {
            _ = try await repository.edit(
                pageID: "page-1",
                corners: [WorkspaceCorner(x: -1, y: 0)],
                filter: .enhance
            )
            XCTFail("非法四角必须被拒绝")
        } catch {
            XCTAssertEqual(error as? WorkspaceError, .invalidCorners)
        }
        XCTAssertEqual(api.editCount, 0)
        XCTAssertEqual(api.reorderCount, 0)
    }

    func testArtifactDownloadVerifiesSizeHashAndUsesUserPartition() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let bytes = Data("verified-pdf".utf8)
        let api = FakeWorkspaceAPI()
        api.artifactDownload = try fixture.remoteDownload(bytes: bytes, mimeType: "application/pdf")
        let repository = fixture.repository(api: api)
        let artifact = workspaceArtifact(bytes: bytes)

        let document = try await repository.downloadArtifact(artifact, userID: "user-a")

        XCTAssertEqual(try Data(contentsOf: document.url), bytes)
        XCTAssertEqual(document.fileName, "扫描结果.pdf")
        XCTAssertTrue(document.url.path.contains(UserStoragePaths.digest(for: "user-a")))
        XCTAssertFalse(document.url.path.contains("user-a"))
    }

    func testArtifactHashMismatchDeletesPartialFile() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let api = FakeWorkspaceAPI()
        api.artifactDownload = try fixture.remoteDownload(bytes: Data("tampered".utf8), mimeType: "application/pdf")
        let repository = fixture.repository(api: api)
        let expected = Data("expected".utf8)

        do {
            _ = try await repository.downloadArtifact(workspaceArtifact(bytes: expected), userID: "user-a")
            XCTFail("摘要不一致必须被拒绝")
        } catch {
            XCTAssertEqual(error as? WorkspaceError, .downloadHashMismatch)
        }
        let userRoot = fixture.downloadRoot.appendingPathComponent(UserStoragePaths.digest(for: "user-a"))
        let files = (try? FileManager.default.subpathsOfDirectory(atPath: userRoot.path)) ?? []
        XCTAssertTrue(files.filter { !$0.hasSuffix("exports") }.isEmpty)
    }

    func testProjectListFallsBackToCurrentUsersCache() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let api = FakeWorkspaceAPI()
        api.projectError = URLError(.notConnectedToInternet)
        let cache = SpyUserCache()
        await cache.replaceProjects(
            [CachedProject(id: "cached-1", title: "离线项目", mode: "document", updatedAt: "2026-10-21")],
            for: "user-a"
        )
        let repository = fixture.repository(api: api, cache: cache)

        let projects = try await repository.projects(userID: "user-a")

        XCTAssertEqual(projects.map(\.id), ["cached-1"])
        XCTAssertEqual(projects.first?.displayName, "离线项目")
    }
}

private struct WorkspaceFixture {
    let root: URL
    let downloadRoot: URL

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-workspace-\(UUID().uuidString)", isDirectory: true)
        downloadRoot = root.appendingPathComponent("downloads", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    func repository(
        api: FakeWorkspaceAPI,
        cache: UserScopedProjectCaching = SpyUserCache()
    ) -> WorkspaceRepository {
        let sessions = TestSessionStore()
        try? sessions.save(token().credentials(userID: "user-a"))
        let authentication = AuthenticationRepository(
            api: StubAuthenticationAPI(),
            sessions: sessions,
            cache: cache
        )
        return WorkspaceRepository(
            api: api,
            authentication: authentication,
            cache: cache,
            root: downloadRoot
        )
    }

    func remoteDownload(bytes: Data, mimeType: String) throws -> RemoteDownload {
        let file = root.appendingPathComponent("remote-\(UUID().uuidString)")
        try bytes.write(to: file)
        return RemoteDownload(temporaryURL: file, suggestedFileName: nil, mimeType: mimeType)
    }

    func cleanup() { try? FileManager.default.removeItem(at: root) }
}

private final class FakeWorkspaceAPI: SmartScanWorkspaceAPI {
    var projectError: Error?
    var artifactDownload: RemoteDownload?
    var editCount = 0
    var reorderCount = 0

    func listProjects() async throws -> [WorkspaceProject] {
        if let projectError { throw projectError }
        return []
    }

    func listPages(projectID: String) async throws -> [WorkspacePage] { [] }
    func listExports(projectID: String) async throws -> [WorkspaceExport] { [] }

    func reorderPages(projectID: String, pageIDs: [String]) async throws -> [WorkspacePage] {
        reorderCount += 1
        return []
    }

    func rotatePage(id: String, degrees: Int) async throws -> WorkspacePage { workspacePage() }

    func editPage(id: String, corners: [WorkspaceCorner], filter: WorkspaceFilter) async throws -> WorkspacePage {
        editCount += 1
        return workspacePage()
    }

    func reviewPage(id: String, confirmed: Bool) async throws -> WorkspacePage { workspacePage() }

    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        workspaceExport()
    }

    func getExport(id: String) async throws -> WorkspaceExport { workspaceExport() }

    func downloadPage(id: String) async throws -> RemoteDownload {
        throw WorkspaceError.localFileUnavailable
    }

    func downloadArtifact(id: String) async throws -> RemoteDownload {
        guard let artifactDownload else { throw WorkspaceError.localFileUnavailable }
        return artifactDownload
    }
}

private func workspacePage() -> WorkspacePage {
    WorkspacePage(
        id: "page-1",
        projectID: "project-1",
        pageNumber: 1,
        qualityWarning: nil,
        rotationDegrees: 0,
        activeResultVersion: 1,
        reviewStatus: "pending",
        ocrStatus: "ready"
    )
}

private func workspaceExport() -> WorkspaceExport {
    WorkspaceExport(
        id: "export-1",
        projectID: "project-1",
        format: "pdf",
        quality: "balanced",
        includeOCRText: true,
        status: "ready",
        pageCount: 1,
        errorCode: nil,
        artifacts: [],
        createdAt: "2026-10-21T00:00:00Z",
        completedAt: "2026-10-21T00:01:00Z"
    )
}

private func workspaceArtifact(bytes: Data) -> WorkspaceExportArtifact {
    WorkspaceExportArtifact(
        id: "artifact-1",
        pageID: nil,
        sequence: 1,
        fileName: "扫描结果.pdf",
        mimeType: "application/pdf",
        sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
        sizeBytes: Int64(bytes.count)
    )
}
