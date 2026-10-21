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

    func testAccountDeletionUsesStrongPurposeAndPurgesCurrentUserData() async throws {
        let api = StubAuthenticationAPI()
        let deletionAPI = StubAccountDeletionAPI()
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-1"))
        let cache = SpyUserCache()
        let purger = SpyLocalDataPurger()
        let repository = AuthenticationRepository(
            api: api,
            sessions: sessions,
            cache: cache,
            accountDeletionAPI: deletionAPI,
            localDataPurger: purger
        )

        _ = try await repository.requestAccountDeletionChallenge(phone: "+8613800001234")
        let outcome = try await repository.requestAccountDeletion(
            phone: "+8613800001234",
            challengeID: "challenge-1",
            code: "123456"
        )

        XCTAssertEqual(deletionAPI.lastPurpose, "account_deletion")
        XCTAssertEqual(deletionAPI.lastRequestPhone, "+8613800001234")
        XCTAssertEqual(outcome.receipt.status, "pending")
        XCTAssertTrue(outcome.localCleanupSucceeded)
        XCTAssertNil(sessions.current())
        let clearedCacheUsers = await cache.clearedUsers
        let purgedUsers = await purger.clearedUsers
        XCTAssertEqual(clearedCacheUsers, ["user-1"])
        XCTAssertEqual(purgedUsers, ["user-1"])
    }

    func testAccountDeletionCancellationIsUnauthenticatedAndUsesSeparatePurpose() async throws {
        let deletionAPI = StubAccountDeletionAPI()
        let repository = AuthenticationRepository(
            api: StubAuthenticationAPI(),
            sessions: TestSessionStore(),
            cache: SpyUserCache(),
            accountDeletionAPI: deletionAPI
        )

        _ = try await repository.requestAccountDeletionCancellationChallenge(phone: "+8613800001234")
        let receipt = try await repository.cancelAccountDeletion(
            phone: "+8613800001234",
            challengeID: "challenge-2",
            code: "654321"
        )

        XCTAssertEqual(deletionAPI.lastPurpose, "account_deletion_cancel")
        XCTAssertEqual(receipt.status, "canceled")
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

final class StubAccountDeletionAPI: SmartScanAccountDeletionAPI {
    var lastPurpose: String?
    var lastRequestPhone: String?

    func requestSMSChallenge(phone: String, purpose: String) async throws -> RegistrationChallenge {
        lastPurpose = purpose
        return RegistrationChallenge(
            challengeID: purpose == "account_deletion" ? "challenge-1" : "challenge-2",
            expiresAt: "2026-10-21T00:05:00Z",
            retryAfterSeconds: 60
        )
    }

    func requestAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionReceipt {
        lastRequestPhone = phone
        return deletionReceipt(status: "pending")
    }

    func cancelAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionReceipt {
        lastRequestPhone = phone
        return deletionReceipt(status: "canceled")
    }
}

actor SpyLocalDataPurger: UserScopedLocalDataPurging {
    private(set) var clearedUsers: [String] = []

    func clearUser(_ userID: String) { clearedUsers.append(userID) }
}

private func deletionReceipt(status: String) -> AccountDeletionReceipt {
    AccountDeletionReceipt(
        id: "deletion-1",
        status: status,
        requestedAt: "2026-10-21T00:00:00Z",
        executeAfter: "2026-10-28T00:00:00Z",
        canceledAt: status == "canceled" ? "2026-10-21T00:02:00Z" : nil,
        completedAt: nil
    )
}
