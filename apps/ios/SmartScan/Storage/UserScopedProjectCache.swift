import Foundation

protocol UserScopedProjectCaching {
    func replaceProjects(_ projects: [CachedProject], for userID: String) async throws
    func projects(for userID: String) async throws -> [CachedProject]
    func clearUser(_ userID: String) async throws
}

actor FileUserScopedProjectCache: UserScopedProjectCaching {
    private let root: URL
    private let fileManager: FileManager
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(root: URL? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        if let root {
            self.root = root
        } else {
            self.root = UserStoragePaths.applicationSupportRoot(fileManager: fileManager)
                .appendingPathComponent("users", isDirectory: true)
        }
    }

    func replaceProjects(_ projects: [CachedProject], for userID: String) throws {
        let directory = directory(for: userID)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try encoder.encode(projects)
        try data.write(to: directory.appendingPathComponent("projects.json"), options: .atomic)
    }

    func projects(for userID: String) throws -> [CachedProject] {
        let file = directory(for: userID).appendingPathComponent("projects.json")
        guard fileManager.fileExists(atPath: file.path) else { return [] }
        return try decoder.decode([CachedProject].self, from: Data(contentsOf: file))
    }

    func clearUser(_ userID: String) throws {
        let target = directory(for: userID)
        guard fileManager.fileExists(atPath: target.path) else { return }
        try fileManager.removeItem(at: target)
    }

    private func directory(for userID: String) -> URL {
        let digest = UserStoragePaths.digest(for: userID)
        return root.appendingPathComponent(digest, isDirectory: true)
    }
}
