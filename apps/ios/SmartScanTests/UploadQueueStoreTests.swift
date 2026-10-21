@testable import SmartScan
import Foundation
import XCTest

final class UploadQueueStoreTests: XCTestCase {
    func testQueuePersistsByUserAndDuplicateCaptureIsIdempotent() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let firstRecord = try fixture.capture(userID: "user-a", id: "capture-a")
        let otherRecord = try fixture.capture(userID: "user-b", id: "capture-b")
        let store = fixture.store()

        try await store.enqueue(
            record: firstRecord,
            ownerUserID: "user-a",
            localProjectID: "local-a",
            title: "文档",
            mode: .document
        )
        try await store.enqueue(
            record: firstRecord,
            ownerUserID: "user-a",
            localProjectID: "local-a",
            title: "文档",
            mode: .document
        )
        try await store.enqueue(
            record: otherRecord,
            ownerUserID: "user-b",
            localProjectID: "local-b",
            title: "书籍",
            mode: .book
        )

        let firstSnapshot = try await store.snapshot(ownerUserID: "user-a")
        let restoredCount = try await fixture.store().pendingCount(ownerUserID: "user-a")
        let otherSnapshot = try await store.snapshot(ownerUserID: "user-b")
        XCTAssertEqual(firstSnapshot.projects.first?.uploads.count, 1)
        XCTAssertEqual(restoredCount, 1)
        XCTAssertEqual(otherSnapshot.projects.first?.uploads.first?.captureID, "capture-b")
    }

    func testQueueRejectsCaptureFromAnotherUserDirectory() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let record = try fixture.capture(userID: "user-b", id: "capture-b")

        do {
            try await fixture.store().enqueue(
                record: record,
                ownerUserID: "user-a",
                localProjectID: "local-a",
                title: "文档",
                mode: .document
            )
            XCTFail("跨用户原图必须被拒绝")
        } catch {
            XCTAssertEqual(error as? UploadQueueStoreError, .captureOutsideUserDirectory)
        }
    }

    func testExpiredSessionRotatesKeyAndClearsRemoteProgress() async throws {
        let fixture = try QueueFixture()
        defer { fixture.cleanup() }
        let store = fixture.store()
        try await store.enqueue(
            record: fixture.capture(userID: "user-a", id: "capture-a"),
            ownerUserID: "user-a",
            localProjectID: "local-a",
            title: "文档",
            mode: .document
        )
        let firstOptional = try await store.nextPending(ownerUserID: "user-a")
        let first = try XCTUnwrap(firstOptional)
        try await store.setUploadSession(
            ownerUserID: "user-a",
            localProjectID: first.0.id,
            uploadID: first.1.id,
            serverUploadID: "remote-1",
            sha256: String(repeating: "a", count: 64),
            uploadedBytes: 20
        )
        try await store.rotateUploadSession(
            ownerUserID: "user-a",
            localProjectID: first.0.id,
            uploadID: first.1.id
        )

        let rotatedOptional = try await store.nextPending(ownerUserID: "user-a")
        let rotated = try XCTUnwrap(rotatedOptional).1
        XCTAssertNotEqual(rotated.idempotencyKey, first.1.idempotencyKey)
        XCTAssertNil(rotated.serverUploadID)
        XCTAssertEqual(rotated.uploadedBytes, 0)
        XCTAssertEqual(rotated.status, .retrying)
    }
}

struct QueueFixture {
    let root: URL
    let queueRoot: URL
    let captureRoot: URL

    init() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-ios-queue-\(UUID().uuidString)", isDirectory: true)
        queueRoot = root.appendingPathComponent("queue", isDirectory: true)
        captureRoot = root.appendingPathComponent("captures", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    func store() -> FileUploadQueueStore {
        FileUploadQueueStore(root: queueRoot, captureRoot: captureRoot)
    }

    func capture(userID: String, id: String, bytes: Data = Data(repeating: 7, count: 40)) throws -> CaptureRecord {
        let directory = captureRoot.appendingPathComponent(UserStoragePaths.digest(for: userID), isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let original = directory.appendingPathComponent("\(id).original.jpg")
        let evidence = directory.appendingPathComponent("\(id).evidence.json")
        try bytes.write(to: original)
        try Data("{}".utf8).write(to: evidence)
        return CaptureRecord(id: id, originalURL: original, evidenceURL: evidence)
    }

    func cleanup() {
        try? FileManager.default.removeItem(at: root)
    }
}
