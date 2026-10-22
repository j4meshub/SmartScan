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

    func testBookSideRetakeValidatesPayloadAndReturnsReplacement() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let api = FakeWorkspaceAPI()
        let repository = fixture.repository(api: api)

        let replacement = try await repository.retakeBookSide(
            pageID: "page-1",
            data: Data([0xff, 0xd8, 0xff, 0xd9]),
            mimeType: "image/jpeg"
        )

        XCTAssertEqual(api.retakeCount, 1)
        XCTAssertEqual(replacement.id, "replacement-page")
        XCTAssertEqual(replacement.bookSide, "left")
    }

    func testAIRequestsRequireConsentVersionAndStableIdempotencyInput() async throws {
        let fixture = try WorkspaceFixture()
        defer { fixture.cleanup() }
        let api = FakeWorkspaceAPI()
        let repository = fixture.repository(api: api)

        do {
            _ = try await repository.updateProjectAI(projectID: "project-1", enabled: true, consentVersion: nil)
            XCTFail("开启 AI 必须携带数据说明版本")
        } catch {
            XCTAssertEqual(error as? WorkspaceError, .invalidAIConsent)
        }
        do {
            _ = try await repository.requestAIEnhancement(
                pageID: "page-1",
                kind: "unknown",
                sourceResultVersion: 1,
                idempotencyKey: "ios-ai.valid-key-1234"
            )
            XCTFail("未知 AI 类型必须被拒绝")
        } catch {
            XCTAssertEqual(error as? WorkspaceError, .invalidAIEnhancementKind)
        }

        let enhancement = try await repository.requestAIEnhancement(
            pageID: "page-1",
            kind: "recommended",
            sourceResultVersion: 1,
            idempotencyKey: "ios-ai.stable-key-1234"
        )

        XCTAssertEqual(enhancement.status, "candidate_ready")
        XCTAssertEqual(api.lastAIIdempotencyKey, "ios-ai.stable-key-1234")
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
    var retakeCount = 0
    var lastAIIdempotencyKey: String?

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

    func dismissExamSuggestion(id: String, resultVersion: Int) async throws -> WorkspacePage { workspacePage() }

    func retakeBookSide(id: String, data: Data, mimeType: String) async throws -> WorkspacePage {
        retakeCount += 1
        var replacement = workspacePage(id: "replacement-page")
        replacement.bookCaptureID = "replacement-page"
        replacement.bookSide = "left"
        replacement.bookSplitStatus = "retake"
        replacement.bookIsCurrent = true
        return replacement
    }

    func bookIntegrity(projectID: String) async throws -> WorkspaceBookIntegrityReport {
        workspaceBookIntegrity(projectID: projectID)
    }

    func decideBookIntegrity(
        projectID: String,
        issueKey: String,
        decision: String
    ) async throws -> WorkspaceBookIntegrityReport {
        workspaceBookIntegrity(projectID: projectID)
    }

    func supplementBookPage(
        projectID: String,
        data: Data,
        mimeType: String,
        insertAt: Int,
        expectedPageLabel: String
    ) async throws -> WorkspacePage {
        workspacePage(id: "supplement-page")
    }

    func assembleBook(
        projectID: String,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        workspaceExport()
    }

    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        workspaceExport()
    }

    func getExport(id: String) async throws -> WorkspaceExport { workspaceExport() }

    func downloadPage(id: String, version: Int?) async throws -> RemoteDownload {
        throw WorkspaceError.localFileUnavailable
    }

    func downloadArtifact(id: String) async throws -> RemoteDownload {
        guard let artifactDownload else { throw WorkspaceError.localFileUnavailable }
        return artifactDownload
    }

    func aiCapabilities() async throws -> WorkspaceAICapabilities {
        WorkspaceAICapabilities(
            available: true,
            businessOrchestrationReady: true,
            executionMode: "mock",
            consentVersion: "2026-10-23.1",
            transmissionNoticeCode: "ai_data_transfer_v1",
            enhancementKinds: ["recommended", "complex_ocr"],
            taskTypes: ["classify_page", "ocr_formula"]
        )
    }

    func updateProjectAI(
        projectID: String,
        enabled: Bool,
        consentVersion: String?
    ) async throws -> WorkspaceProject {
        workspaceProject(aiEnabled: enabled, consentVersion: consentVersion)
    }

    func createAIEnhancement(
        pageID: String,
        kind: String,
        sourceResultVersion: Int,
        idempotencyKey: String
    ) async throws -> WorkspaceAIEnhancement {
        lastAIIdempotencyKey = idempotencyKey
        return workspaceAIEnhancement(kind: kind, sourceVersion: sourceResultVersion)
    }

    func listAIEnhancements(pageID: String) async throws -> [WorkspaceAIEnhancement] {
        [workspaceAIEnhancement()]
    }

    func decideAIEnhancement(id: String, accepted: Bool) async throws -> WorkspaceAIEnhancement {
        workspaceAIEnhancement(status: accepted ? "accepted" : "rejected")
    }
}

private func workspaceProject(aiEnabled: Bool = false, consentVersion: String? = nil) -> WorkspaceProject {
    WorkspaceProject(
        id: "project-1",
        title: "Scan",
        suggestedName: nil,
        mode: "document",
        readingOrder: "ltr",
        createdAt: "2026-10-23T00:00:00Z",
        updatedAt: "2026-10-23T00:00:00Z",
        aiEnabled: aiEnabled,
        aiConsentVersion: consentVersion
    )
}

private func workspaceAIEnhancement(
    kind: String = "recommended",
    sourceVersion: Int = 1,
    status: String = "candidate_ready"
) -> WorkspaceAIEnhancement {
    WorkspaceAIEnhancement(
        id: "enhancement-1",
        projectID: "project-1",
        pageID: "page-1",
        processingJobID: nil,
        enhancementKind: kind,
        requestedTasks: ["extract_title"],
        sourceResultVersion: sourceVersion,
        status: status,
        candidates: [.init(kind: "title", value: "Candidate", confidence: 0.9)],
        confidence: 0.9,
        errorCode: nil,
        createdAt: "2026-10-23T00:00:00Z",
        updatedAt: "2026-10-23T00:00:01Z"
    )
}

private func workspaceBookIntegrity(projectID: String) -> WorkspaceBookIntegrityReport {
    WorkspaceBookIntegrityReport(
        projectID: projectID,
        pagesChecked: 1,
        includedPageCount: 1,
        visiblePageNumberCount: 1,
        processingPageCount: 0,
        blockingIssueCount: 0,
        readyToAssemble: true,
        issues: []
    )
}

private func workspacePage(id: String = "page-1") -> WorkspacePage {
    WorkspacePage(
        id: id,
        projectID: "project-1",
        pageNumber: 1,
        qualityWarning: nil,
        rotationDegrees: 0,
        activeResultVersion: 1,
        reviewStatus: "pending",
        ocrStatus: "ready",
        examResultVersion: nil,
        examConfidenceBand: nil,
        examRecommendation: nil,
        examSuggestionVisible: nil
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
