@testable import SmartScan
import Foundation
import XCTest

final class CaptureStoreTests: XCTestCase {
    func testOriginalAndEvidenceAreStoredInsideOnlyTheOwningUserPartition() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-ios-captures-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = FileOriginalCaptureStore(root: root)
        let evidence = makeEvidence()

        let first = try await store.saveOriginal(Data([0xff, 0xd8, 0xff, 0xd9]), evidence: evidence, userID: "user-a")
        let second = try await store.saveOriginal(Data([0xff, 0xd8, 0xff, 0xd9]), evidence: evidence, userID: "user-b")

        XCTAssertNotEqual(first.originalURL.deletingLastPathComponent(), second.originalURL.deletingLastPathComponent())
        XCTAssertFalse(first.originalURL.path.contains("user-a"))
        XCTAssertEqual(try Data(contentsOf: first.originalURL), Data([0xff, 0xd8, 0xff, 0xd9]))
        let restored = try JSONDecoder().decode(CaptureEvidence.self, from: Data(contentsOf: first.evidenceURL))
        XCTAssertEqual(restored, evidence)
    }

    func testEmptyOriginalIsRejectedWithoutCreatingEvidence() async {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-ios-empty-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = FileOriginalCaptureStore(root: root)

        do {
            _ = try await store.saveOriginal(Data(), evidence: makeEvidence(), userID: "user-a")
            XCTFail("空原图必须被拒绝")
        } catch {
            XCTAssertEqual(error as? CaptureStoreError, .emptyImage)
            XCTAssertFalse(FileManager.default.fileExists(atPath: root.path))
        }
    }

    private func makeEvidence() -> CaptureEvidence {
        CaptureEvidence(
            capturedAt: "2026-10-21T05:00:00Z",
            mode: .document,
            deviceOrientation: .landscapeLeft,
            exifOrientation: 1,
            pixelWidth: 3024,
            pixelHeight: 4032,
            quality: FrameQuality(
                brightness: 0.5,
                sharpness: 0.2,
                highlightRatio: 0.01,
                rectangleConfidence: 0.9,
                issues: []
            ),
            rectangle: NormalizedQuadrilateral(
                topLeft: CGPoint(x: 0.1, y: 0.9),
                topRight: CGPoint(x: 0.9, y: 0.9),
                bottomRight: CGPoint(x: 0.9, y: 0.1),
                bottomLeft: CGPoint(x: 0.1, y: 0.1)
            )
        )
    }
}
