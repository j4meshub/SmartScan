import Combine
import Foundation

@MainActor
final class AuthenticationStore: ObservableObject {
    enum Phase: Equatable {
        case restoring
        case signedOut
        case signedIn(UserProfile)
    }

    @Published private(set) var phase: Phase = .restoring
    @Published private(set) var busy = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var challenge: RegistrationChallenge?

    private let repository: AuthenticationRepository

    init(repository: AuthenticationRepository) {
        self.repository = repository
    }

    func restore() async {
        do {
            phase = try await repository.restore().map(Phase.signedIn) ?? .signedOut
        } catch {
            phase = .signedOut
            errorMessage = message(for: error)
        }
    }

    func login(username: String, password: String) async {
        await perform {
            self.phase = .signedIn(try await self.repository.login(username: username, password: password))
        }
    }

    func requestRegistrationCode(phone: String) async {
        await perform {
            self.challenge = try await self.repository.requestRegistrationChallenge(phone: phone)
        }
    }

    func register(phone: String, code: String, username: String, password: String) async {
        guard let challenge else {
            errorMessage = String(localized: "Request a verification code first.")
            return
        }
        let language = Locale.current.language.languageCode?.identifier == "zh" ? "zh-CN" : "en"
        let input = RegistrationInput(
            phone: phone,
            code: code,
            challengeID: challenge.challengeID,
            username: username,
            password: password,
            locale: language
        )
        await perform {
            self.phase = .signedIn(try await self.repository.register(input))
            self.challenge = nil
        }
    }

    func logout() async {
        busy = true
        defer { busy = false }
        do {
            try await repository.logout()
        } catch {
            errorMessage = String(localized: "Signed out locally. The server could not be reached.")
        }
        phase = .signedOut
        challenge = nil
    }

    func clearError() {
        errorMessage = nil
    }

    private func perform(_ operation: () async throws -> Void) async {
        busy = true
        errorMessage = nil
        defer { busy = false }
        do {
            try await operation()
        } catch {
            errorMessage = message(for: error)
        }
    }

    private func message(for error: Error) -> String {
        if let apiError = error as? APIClientError {
            if case .http(statusCode: 401, detail: _) = apiError {
                return String(localized: "Incorrect username or password.")
            }
            if case .http(statusCode: 409, detail: _) = apiError {
                return String(localized: "This username or phone number is already in use.")
            }
        }
        if error is AuthenticationError {
            return String(localized: "Complete all required fields.")
        }
        return String(localized: "Unable to connect. Try again later.")
    }
}
