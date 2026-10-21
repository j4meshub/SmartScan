import XCTest
@testable import SmartScan

final class ScanModeKindTests: XCTestCase {
    func testScanModesKeepStableIdentifiersAndOrder() {
        XCTAssertEqual(
            ScanModeKind.allCases.map(\.rawValue),
            ["document", "exam", "book"]
        )
    }

    func testEveryScanModeHasVisibleContent() {
        for mode in ScanModeKind.allCases {
            XCTAssertFalse(mode.title.isEmpty)
            XCTAssertFalse(mode.subtitle.isEmpty)
        }
    }
}
