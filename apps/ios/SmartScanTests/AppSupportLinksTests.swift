import XCTest
@testable import SmartScan

final class AppSupportLinksTests: XCTestCase {
    func testReleaseHTTPSLinksAreExposed() {
        let links = AppSupportLinks(info: [
            "SMARTSCAN_PRIVACY_POLICY_URL": "https://smartscan.example/privacy",
            "SMARTSCAN_SUPPORT_URL": "https://smartscan.example/support",
        ])

        XCTAssertEqual(links.privacyPolicy?.absoluteString, "https://smartscan.example/privacy")
        XCTAssertEqual(links.support?.absoluteString, "https://smartscan.example/support")
    }

    func testPlaceholderAndInsecureLinksStayHidden() {
        let links = AppSupportLinks(info: [
            "SMARTSCAN_PRIVACY_POLICY_URL": "https://privacy.example.invalid/",
            "SMARTSCAN_SUPPORT_URL": "http://smartscan.example/support",
        ])

        XCTAssertNil(links.privacyPolicy)
        XCTAssertNil(links.support)
    }
}
