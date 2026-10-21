import Foundation

actor AuthenticationRepository {
    private let api: SmartScanAuthenticationAPI
    private let sessions: SessionStoring
    private let cache: UserScopedProjectCaching

    init(api: SmartScanAuthenticationAPI, sessions: SessionStoring, cache: UserScopedProjectCaching) {
        self.api = api
        self.sessions = sessions
        self.cache = cache
    }

    func requestRegistrationChallenge(phone: String) async throws -> RegistrationChallenge {
        guard !phone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw AuthenticationError.invalidInput
        }
        return try await api.requestRegistrationChallenge(phone: phone)
    }

    func register(_ input: RegistrationInput) async throws -> UserProfile {
        try await authenticate { try await api.register(input) }
    }

    func login(username: String, password: String) async throws -> UserProfile {
        guard !username.isEmpty, !password.isEmpty else { throw AuthenticationError.invalidInput }
        return try await authenticate { try await api.login(username: username, password: password) }
    }

    func restore() async throws -> UserProfile? {
        guard sessions.current() != nil else { return nil }
        do {
            return try await api.currentUser()
        } catch APIClientError.http(statusCode: 401, detail: _) {
            do {
                _ = try await refresh()
                return try await api.currentUser()
            } catch {
                await clearLocalSession()
                throw error
            }
        }
    }

    func refresh() async throws -> SessionCredentials {
        guard let current = sessions.current() else { throw AuthenticationError.sessionMissing }
        do {
            let token = try await api.refresh(refreshToken: current.refreshToken)
            let replacement = try token.credentials(userID: current.userID)
            try sessions.save(replacement)
            return replacement
        } catch {
            if let apiError = error as? APIClientError,
               case .http(statusCode: 401, detail: _) = apiError {
                await clearLocalSession()
            }
            throw error
        }
    }

    func logout() async throws {
        let remoteError: Error?
        do {
            try await api.logout()
            remoteError = nil
        } catch {
            remoteError = error
        }
        await clearLocalSession()
        if let remoteError { throw remoteError }
    }

    private func authenticate(_ request: () async throws -> TokenResponse) async throws -> UserProfile {
        let token = try await request()
        let provisional = try token.credentials()
        do {
            try sessions.save(provisional)
            let user = try await api.currentUser()
            try sessions.save(provisional.assigning(userID: user.id))
            return user
        } catch {
            try? sessions.clear()
            throw error
        }
    }

    private func clearLocalSession() async {
        let userID = sessions.current()?.userID
        try? sessions.clear()
        if let userID { try? await cache.clearUser(userID) }
    }
}

enum AuthenticationError: Error, Equatable {
    case invalidInput
    case sessionMissing
}
