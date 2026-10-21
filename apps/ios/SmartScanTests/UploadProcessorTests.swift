@testable import SmartScan
import Foundation
import XCTest

final class UploadProcessorTests: XCTestCase {
    func testProcessorSkipsOnlyServerConfirmedChunksAndCompletes() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let remote = FakeUploadAPI()
        remote.createdUpload = remoteUpload(receivedChunks: [0, 2])
        let processor = try makeProcessor(queue: queue, remote: remote, userID: "user-a")

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .completed)
        XCTAssertEqual(remote.chunkIndexes, [1, 3])
        XCTAssertEqual(remote.completedUploadIDs, ["upload-1"])
        let snapshot = try await queue.snapshot(ownerUserID: "user-a")
        let upload = try XCTUnwrap(snapshot.projects.first?.uploads.first)
        XCTAssertEqual(upload.status, .completed)
        XCTAssertEqual(upload.pageID, "page-1")
        XCTAssertEqual(upload.uploadedBytes, 40)
    }

    func testCompletedRemoteUploadConvergesWithoutSendingChunksAgain() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let pendingOptional = try await queue.nextPending(ownerUserID: "user-a")
        let pending = try XCTUnwrap(pendingOptional)
        try await queue.setServerProjectID(ownerUserID: "user-a", localProjectID: "local-a", serverProjectID: "project-1")
        try await queue.setUploadSession(
            ownerUserID: "user-a",
            localProjectID: "local-a",
            uploadID: pending.1.id,
            serverUploadID: "upload-1",
            sha256: String(repeating: "a", count: 64),
            uploadedBytes: 10
        )
        let remote = FakeUploadAPI()
        remote.loadedUpload = remoteUpload(status: "completed", pageID: "page-existing")
        let processor = try makeProcessor(queue: queue, remote: remote, userID: "user-a")

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .completed)
        XCTAssertTrue(remote.chunkIndexes.isEmpty)
        XCTAssertTrue(remote.completedUploadIDs.isEmpty)
        let snapshot = try await queue.snapshot(ownerUserID: "user-a")
        XCTAssertEqual(snapshot.projects.first?.uploads.first?.pageID, "page-existing")
    }

    func testUnauthorizedRequestRefreshesOnceAndRetries() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let remote = FakeUploadAPI()
        remote.createProjectErrors = [APIClientError.http(statusCode: 401, detail: "expired")]
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-a"))
        let authAPI = StubAuthenticationAPI()
        authAPI.refreshToken = token(access: "access-2", refresh: "refresh-2")
        let authentication = AuthenticationRepository(api: authAPI, sessions: sessions, cache: SpyUserCache())
        let processor = UploadProcessor(api: remote, queue: queue, sessions: sessions, authentication: authentication)

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .completed)
        XCTAssertEqual(remote.createProjectCount, 2)
        XCTAssertEqual(sessions.current()?.refreshToken, "refresh-2")
    }

    func testDifferentSignedInUserCannotTakeOverQueue() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let processor = try makeProcessor(queue: queue, remote: FakeUploadAPI(), userID: "user-b")

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .waitingForLogin)
        let snapshot = try await queue.snapshot(ownerUserID: "user-a")
        XCTAssertEqual(snapshot.projects.first?.uploads.first?.status, .waitingForLogin)
    }

    func testOfflineRetryKeepsUploadSessionAndIdempotencyKey() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let beforeOptional = try await queue.nextPending(ownerUserID: "user-a")
        let before = try XCTUnwrap(beforeOptional).1
        let remote = FakeUploadAPI()
        remote.putChunkError = URLError(.notConnectedToInternet)
        let processor = try makeProcessor(queue: queue, remote: remote, userID: "user-a")

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .retry)
        let afterOptional = try await queue.nextPending(ownerUserID: "user-a")
        let after = try XCTUnwrap(afterOptional).1
        XCTAssertEqual(after.status, .retrying)
        XCTAssertEqual(after.idempotencyKey, before.idempotencyKey)
        XCTAssertEqual(after.serverUploadID, "upload-1")
        XCTAssertEqual(after.uploadedBytes, 0)
    }

    func testInvalidChunkReceiptFailsWithoutCompletingUpload() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let queue = fixture.store()
        try await enqueueFixture(queue: queue, fixture: fixture)
        let remote = FakeUploadAPI()
        remote.receiptSizeAdjustment = 1
        let processor = try makeProcessor(queue: queue, remote: remote, userID: "user-a")

        let result = await processor.processNext(ownerUserID: "user-a")

        XCTAssertEqual(result, .failed)
        XCTAssertTrue(remote.completedUploadIDs.isEmpty)
        let snapshot = try await queue.snapshot(ownerUserID: "user-a")
        XCTAssertEqual(snapshot.projects.first?.uploads.first?.status, .failed)
    }

    private func enqueueFixture(queue: FileUploadQueueStore, fixture: QueueFixture) async throws {
        try await queue.enqueue(
            record: fixture.capture(userID: "user-a", id: "capture-a"),
            ownerUserID: "user-a",
            localProjectID: "local-a",
            title: "文档",
            mode: .document
        )
    }

    private func makeProcessor(
        queue: FileUploadQueueStore,
        remote: FakeUploadAPI,
        userID: String
    ) throws -> UploadProcessor {
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: userID))
        let authentication = AuthenticationRepository(
            api: StubAuthenticationAPI(),
            sessions: sessions,
            cache: SpyUserCache()
        )
        return UploadProcessor(api: remote, queue: queue, sessions: sessions, authentication: authentication)
    }
}

final class FakeUploadAPI: SmartScanUploadAPI {
    var createdUpload = remoteUpload()
    var loadedUpload = remoteUpload()
    var createProjectErrors: [Error] = []
    var createProjectCount = 0
    var chunkIndexes: [Int] = []
    var completedUploadIDs: [String] = []
    var putChunkError: Error?
    var receiptSizeAdjustment: Int64 = 0

    func createProject(title: String, mode: ScanModeKind) async throws -> RemoteProject {
        createProjectCount += 1
        if !createProjectErrors.isEmpty { throw createProjectErrors.removeFirst() }
        return RemoteProject(id: "project-1")
    }

    func createUpload(_ request: RemoteUploadCreate) async throws -> RemoteUpload { createdUpload }
    func getUpload(id: String) async throws -> RemoteUpload { loadedUpload }

    func putChunk(uploadID: String, index: Int, sha256: String, data: Data) async throws -> RemoteChunkReceipt {
        if let putChunkError { throw putChunkError }
        chunkIndexes.append(index)
        return RemoteChunkReceipt(
            uploadID: uploadID,
            chunkIndex: index,
            sizeBytes: Int64(data.count) + receiptSizeAdjustment,
            sha256: sha256
        )
    }

    func completeUpload(id: String) async throws -> RemotePage {
        completedUploadIDs.append(id)
        return RemotePage(id: "page-1")
    }
}

func remoteUpload(
    receivedChunks: [Int] = [],
    status: String = "pending",
    pageID: String? = nil
) -> RemoteUpload {
    RemoteUpload(
        id: "upload-1",
        projectID: "project-1",
        fileName: "capture.jpg",
        mimeType: "image/jpeg",
        sizeBytes: 40,
        chunkSize: 10,
        totalChunks: 4,
        receivedChunks: receivedChunks,
        status: status,
        pageID: pageID,
        expiresAt: "2026-10-22T00:00:00Z"
    )
}
