import SwiftUI

struct AuthenticationView: View {
    private enum Mode { case login, register }

    @ObservedObject var authentication: AuthenticationStore
    @State private var mode: Mode = .login
    @State private var username = ""
    @State private var password = ""
    @State private var phone = ""
    @State private var code = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(String(localized: "Username"), text: $username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField(String(localized: "Password"), text: $password)
                    if mode == .register {
                        TextField(String(localized: "Phone number"), text: $phone)
                            .keyboardType(.phonePad)
                        HStack {
                            TextField(String(localized: "Verification code"), text: $code)
                                .keyboardType(.numberPad)
                            Button(String(localized: "Send code")) {
                                Task { await authentication.requestRegistrationCode(phone: phone) }
                            }
                            .disabled(authentication.busy || phone.isEmpty)
                        }
                        if let challenge = authentication.challenge {
                            Text(String(format: String(localized: "Code sent. Retry in %d seconds."), challenge.retryAfterSeconds))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if let message = authentication.errorMessage {
                    Section {
                        Text(message).foregroundStyle(.red)
                    }
                }

                Section {
                    Button(mode == .login ? String(localized: "Log in") : String(localized: "Create account")) {
                        Task {
                            if mode == .login {
                                await authentication.login(username: username, password: password)
                            } else {
                                await authentication.register(
                                    phone: phone,
                                    code: code,
                                    username: username,
                                    password: password
                                )
                            }
                        }
                    }
                    .disabled(authentication.busy || username.isEmpty || password.isEmpty)

                    Button(mode == .login ? String(localized: "Create an account") : String(localized: "Use an existing account")) {
                        mode = mode == .login ? .register : .login
                        authentication.clearError()
                    }
                    .disabled(authentication.busy)
                }
            }
            .navigationTitle(mode == .login ? String(localized: "Log in") : String(localized: "Register"))
            .overlay { if authentication.busy { ProgressView() } }
        }
    }
}
