import SwiftUI

struct AccountManagementView: View {
    let user: UserProfile
    @ObservedObject var authentication: AuthenticationStore
    @Environment(\.dismiss) private var dismiss
    @State private var phone = ""
    @State private var code = ""
    @State private var confirmUsername = ""

    var body: some View {
        NavigationStack {
            Form {
                Section(String(localized: "Account")) {
                    LabeledContent(String(localized: "Username"), value: user.username)
                    LabeledContent(String(localized: "Phone number"), value: user.phoneMasked)
                    Button(String(localized: "Log out"), role: .destructive) {
                        Task { await authentication.logout() }
                    }
                    .disabled(authentication.busy)
                }

                if AppSupportLinks.current.privacyPolicy != nil || AppSupportLinks.current.support != nil {
                    Section(String(localized: "Help and privacy")) {
                        if let privacyPolicy = AppSupportLinks.current.privacyPolicy {
                            Link(String(localized: "Privacy policy"), destination: privacyPolicy)
                        }
                        if let support = AppSupportLinks.current.support {
                            Link(String(localized: "Support"), destination: support)
                        }
                    }
                }

                Section(String(localized: "Delete account")) {
                    Text(String(localized: "Deletion starts after a 7-day cooling-off period. Signing in again does not cancel it; use the cancellation flow with SMS verification."))
                        .foregroundStyle(.red)
                    TextField(String(localized: "Phone number in E.164 format"), text: $phone)
                        .keyboardType(.phonePad)
                    HStack {
                        TextField(String(localized: "Verification code"), text: $code)
                            .keyboardType(.numberPad)
                        Button(String(localized: "Send code")) {
                            Task { await authentication.requestAccountDeletionCode(phone: phone) }
                        }
                        .disabled(authentication.busy || phone.isEmpty)
                    }
                    if let challenge = authentication.deletionChallenge {
                        Text(String(format: String(localized: "Code sent. Retry in %d seconds."), challenge.retryAfterSeconds))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    TextField(String(localized: "Enter username to confirm"), text: $confirmUsername)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(String(localized: "Schedule account deletion"), role: .destructive) {
                        Task {
                            await authentication.requestAccountDeletion(
                                user: user,
                                phone: phone,
                                code: code,
                                confirmUsername: confirmUsername
                            )
                        }
                    }
                    .disabled(authentication.busy || phone.isEmpty || code.isEmpty || confirmUsername.isEmpty)
                }

                if let message = authentication.errorMessage {
                    Section { Text(message).foregroundStyle(.red) }
                }
            }
            .navigationTitle(String(localized: "Manage account"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(String(localized: "Done")) { dismiss() }
                }
            }
            .overlay { if authentication.busy { ProgressView() } }
            .onAppear { authentication.clearError() }
        }
    }
}
