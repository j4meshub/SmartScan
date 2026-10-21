import Foundation

struct AppSupportLinks: Equatable {
    let privacyPolicy: URL?
    let support: URL?

    static var current: AppSupportLinks {
        AppSupportLinks(info: Bundle.main.infoDictionary ?? [:])
    }

    init(info: [String: Any]) {
        privacyPolicy = Self.releaseURL(info["SMARTSCAN_PRIVACY_POLICY_URL"] as? String)
        support = Self.releaseURL(info["SMARTSCAN_SUPPORT_URL"] as? String)
    }

    private static func releaseURL(_ value: String?) -> URL? {
        guard let value,
              let url = URL(string: value),
              url.scheme?.lowercased() == "https",
              let host = url.host?.lowercased(),
              !host.hasSuffix(".invalid")
        else {
            return nil
        }
        return url
    }
}
