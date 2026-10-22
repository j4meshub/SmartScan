@testable import SmartScan
import XCTest

final class WorkspaceAIStateTests: XCTestCase {
    func testCurrentVersionCandidateWinsAndOnlyReadyCandidateCanBeDecided() {
        let history = [
            enhancement(id: "old", sourceVersion: 1, status: "accepted"),
            enhancement(id: "current", sourceVersion: 2, status: "candidate_ready"),
        ]

        let current = latestAIEnhancement(history, sourceVersion: 2, enhancementKind: "recommended")

        XCTAssertEqual(current?.id, "current")
        XCTAssertTrue(canDecideAIEnhancement(current, activeResultVersion: 2))
        XCTAssertFalse(canDecideAIEnhancement(current, activeResultVersion: 3))
    }

    func testPollingAndCapabilityRulesMatchOtherClients() {
        let capabilities = WorkspaceAICapabilities(
            available: true,
            businessOrchestrationReady: true,
            executionMode: "mock",
            consentVersion: "2026-10-23.1",
            transmissionNoticeCode: "ai_data_transfer_v1",
            enhancementKinds: ["recommended", "complex_ocr"],
            taskTypes: ["classify_page", "ocr_formula"]
        )

        XCTAssertTrue(shouldPollAIEnhancements([enhancement(status: "processing")]))
        XCTAssertFalse(shouldPollAIEnhancements([enhancement(status: "candidate_ready")]))
        XCTAssertTrue(supportsAIEnhancement(capabilities, kind: "recommended"))
        XCTAssertTrue(supportsAIEnhancement(capabilities, kind: "complex_ocr"))
        XCTAssertFalse(supportsAIEnhancement(capabilities, kind: "unknown"))
        XCTAssertEqual(aiConfidencePercent(0.915), 92)
    }

    func testIdempotencyKeyBindsPageAndVersionWithoutUnsafeCharacters() throws {
        let key = try makeAIIdempotencyKey(
            pageID: "page/用户 1",
            sourceResultVersion: 7,
            randomID: "fixed-random"
        )

        XCTAssertEqual(key, "ios-ai.page____1.v7.fixed-random")
        XCTAssertTrue((16 ... 100).contains(key.count))
    }
}

private func enhancement(
    id: String = "enhancement-1",
    sourceVersion: Int = 1,
    status: String
) -> WorkspaceAIEnhancement {
    WorkspaceAIEnhancement(
        id: id,
        projectID: "project-1",
        pageID: "page-1",
        processingJobID: nil,
        enhancementKind: "recommended",
        requestedTasks: ["extract_title"],
        sourceResultVersion: sourceVersion,
        status: status,
        candidates: [],
        confidence: nil,
        errorCode: nil,
        createdAt: "2026-10-23T00:00:00Z",
        updatedAt: "2026-10-23T00:00:01Z"
    )
}
