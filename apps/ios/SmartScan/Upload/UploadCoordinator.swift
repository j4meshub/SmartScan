import Foundation

protocol UploadBackgroundScheduling: AnyObject {
    func schedule()
}

actor UploadCoordinator {
    private let queue: FileUploadQueueStore
    private let processor: UploadProcessor
    private let sessions: SessionStoring
    private let scheduler: UploadBackgroundScheduling

    init(
        queue: FileUploadQueueStore,
        processor: UploadProcessor,
        sessions: SessionStoring,
        scheduler: UploadBackgroundScheduling
    ) {
        self.queue = queue
        self.processor = processor
        self.sessions = sessions
        self.scheduler = scheduler
    }

    func enqueue(
        record: CaptureRecord,
        ownerUserID: String,
        localProjectID: String,
        title: String,
        mode: ScanModeKind
    ) async -> Bool {
        do {
            try await queue.enqueue(
                record: record,
                ownerUserID: ownerUserID,
                localProjectID: localProjectID,
                title: title,
                mode: mode
            )
            scheduler.schedule()
            _ = await processAll(ownerUserID: ownerUserID)
            return true
        } catch {
            return false
        }
    }

    func resumeCurrentUser() async -> Bool {
        guard let userID = sessions.current()?.userID else { return false }
        scheduler.schedule()
        return await processAll(ownerUserID: userID)
    }

    func processAll(ownerUserID: String) async -> Bool {
        guard sessions.current()?.userID == ownerUserID else { return false }
        while !Task.isCancelled {
            switch await processor.processNext(ownerUserID: ownerUserID) {
            case .completed: continue
            case .empty: return true
            case .retry, .waitingForLogin:
                scheduler.schedule()
                return false
            case .failed: continue
            }
        }
        scheduler.schedule()
        return false
    }
}
