@testable import SmartScan
import Foundation
import XCTest

final class AuthenticationRepositoryTests: XCTestCase {
    func testLoginPersistsUserOnlyAfterProfileLoads() async throws {
        let api = StubAuthenticationAPI()
        let sessions = TestSessionStore()
        let cache = SpyUserCache()
        let repository = AuthenticationRepository(api: api, sessions: sessions, cache: cache)

        let profile = try await repository.login(username: "student", password: "private-password")

        XCTAssertEqual(profile.id, "user-1")
        XCTAssertEqual(sessions.current()?.userID, "user-1")
    }

    func testRestoreRefreshesOnceAfterUnauthorizedResponse() async throws {
        let api = StubAuthenticationAPI()
        api.currentUserResults = [
            .failure(APIClientError.http(statusCode: 401, detail: "token_expired")),
            .success(user()),
        ]
        api.refreshToken = token(access: "access-2", refresh: "refresh-2")
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-1"))
        let repository = AuthenticationRepository(api: api, sessions: sessions, cache: SpyUserCache())

        let restored = try await repository.restore()

        XCTAssertEqual(restored?.id, "user-1")
        XCTAssertEqual(api.lastRefreshToken, "refresh-1")
        XCTAssertEqual(sessions.current()?.refreshToken, "refresh-2")
    }

    func testFailedLogoutStillClearsSessionAndOnlyCurrentUserCache() async throws {
        let api = StubAuthenticationAPI()
        api.logoutError = URLError(.notConnectedToInternet)
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-1"))
        let cache = SpyUserCache()
        let repository = AuthenticationRepository(api: api, sessions: sessions, cache: cache)

        do {
            try await repository.logout()
            XCTFail("网络错误应返回给界面")
        } catch {
            let clearedUsers = await cache.clearedUsers
            XCTAssertNil(sessions.current())
            XCTAssertEqual(clearedUsers, ["user-1"])
        }
    }
}

final class StubAuthenticationAPI: SmartScanAuthenticationAPI {
    var currentUserResults: [Result<UserProfile, Error>] = [.success(user())]
    var refreshToken = token()
    var logoutError: Error?
    var lastRefreshToken: String?

    func requestRegistrationChallenge(phone: String) async throws -> RegistrationChallenge {
        RegistrationChallenge(challengeID: "challenge-1", expiresAt: "2026-10-21T00:05:00Z", retryAfterSeconds: 60)
    }

    func register(_ input: RegistrationInput) async throws -> TokenResponse { token() }
    func login(username: String, password: String) async throws -> TokenResponse { token() }

    func refresh(refreshToken: String) async throws -> TokenResponse {
        lastRefreshToken = refreshToken
        return self.refreshToken
    }

    func currentUser() async throws -> UserProfile {
        try currentUserResults.removeFirst().get()
    }

    func logout() async throws {
        if let logoutError { throw logoutError }
    }
}

actor SpyUserCache: UserScopedProjectCaching {
    private(set) var clearedUsers: [String] = []
    private var projectsByUser: [String: [CachedProject]] = [:]

    func replaceProjects(_ projects: [CachedProject], for userID: String) {
        projectsByUser[userID] = projects
    }

    func projects(for userID: String) -> [CachedProject] {
        projectsByUser[userID] ?? []
    }

    func clearUser(_ userID: String) {
        clearedUsers.append(userID)
        projectsByUser[userID] = nil
    }
}
