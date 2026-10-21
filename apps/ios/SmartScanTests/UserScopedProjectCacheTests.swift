@testable import SmartScan
import Foundation
import XCTest

final class UserScopedProjectCacheTests: XCTestCase {
    func testProjectsArePartitionedAndClearedPerUser() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-ios-cache-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = FileUserScopedProjectCache(root: root)
        let first = CachedProject(id: "p1", title: "甲", mode: "document", updatedAt: "2026-10-21T00:00:00Z")
        let second = CachedProject(id: "p2", title: "乙", mode: "book", updatedAt: "2026-10-21T00:01:00Z")

        try await cache.replaceProjects([first], for: "user-a")
        try await cache.replaceProjects([second], for: "user-b")
        try await cache.clearUser("user-a")

        let firstProjects = try await cache.projects(for: "user-a")
        let secondProjects = try await cache.projects(for: "user-b")
        XCTAssertEqual(firstProjects, [])
        XCTAssertEqual(secondProjects, [second])
        XCTAssertFalse(root.path.contains("user-a"))
    }
}
