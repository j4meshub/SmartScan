import Foundation

protocol UserScopedLocalDataPurging: Sendable {
    func clearUser(_ userID: String) async throws
}

actor FileUserLocalDataPurger: UserScopedLocalDataPurging {
    private let roots: [URL]
    private let fileManager: FileManager

    init(roots: [URL]? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        let support = UserStoragePaths.applicationSupportRoot(fileManager: fileManager)
        self.roots = roots ?? ["users", "captures", "upload-queue", "downloads"].map {
            support.appendingPathComponent($0, isDirectory: true)
        }
    }

    func clearUser(_ userID: String) throws {
        guard !userID.isEmpty else { return }
        let digest = UserStoragePaths.digest(for: userID)
        for root in roots {
            let target = root.appendingPathComponent(digest, isDirectory: true)
            guard UserStoragePaths.isDescendant(target, of: root) else { continue }
            if fileManager.fileExists(atPath: target.path) {
                try fileManager.removeItem(at: target)
            }
        }
    }
}
