@testable import SmartScan
import XCTest

final class IdentityModelsTests: XCTestCase {
    func testBearerTokenRequiresCompleteRotatingSession() throws {
        let credentials = try token().credentials(userID: "user-1")

        XCTAssertEqual(credentials.accessToken, "access-1")
        XCTAssertEqual(credentials.refreshToken, "refresh-1")
        XCTAssertEqual(credentials.userID, "user-1")
    }

    func testLegacyTokenWithoutRefreshFieldsIsRejected() {
        let response = TokenResponse(
            accessToken: "access",
            tokenType: "bearer",
            expiresAt: "2026-10-21T01:00:00Z",
            refreshToken: nil,
            refreshExpiresAt: nil,
            sessionID: nil,
            deviceID: nil
        )

        XCTAssertThrowsError(try response.credentials()) { error in
            XCTAssertEqual(error as? IdentityValidationError, .incompleteSession)
        }
    }
}

func token(access: String = "access-1", refresh: String = "refresh-1") -> TokenResponse {
    TokenResponse(
        accessToken: access,
        tokenType: "bearer",
        expiresAt: "2026-10-21T01:00:00Z",
        refreshToken: refresh,
        refreshExpiresAt: "2026-11-21T01:00:00Z",
        sessionID: "session-1",
        deviceID: "ios:test-device"
    )
}

func user(id: String = "user-1") -> UserProfile {
    UserProfile(
        id: id,
        username: "student",
        phoneMasked: "138****0000",
        role: "user",
        status: "active",
        locale: "zh-CN",
        mustChangePassword: false,
        createdAt: "2026-10-21T00:00:00Z"
    )
}
