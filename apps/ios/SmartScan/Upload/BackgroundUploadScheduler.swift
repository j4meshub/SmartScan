import BackgroundTasks
import Foundation

final class BackgroundUploadScheduler: UploadBackgroundScheduling {
    static let identifier = Bundle.main.object(
        forInfoDictionaryKey: "SMARTSCAN_BACKGROUND_TASK_IDENTIFIER"
    ) as? String ?? "com.j4meshub.smartscan.upload"
    private weak var coordinatorReference: CoordinatorReference?

    func register(coordinator: UploadCoordinator) {
        let reference = CoordinatorReference(coordinator: coordinator)
        coordinatorReference = reference
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.identifier, using: nil) { [weak self, reference] task in
            guard let processingTask = task as? BGProcessingTask else {
                task.setTaskCompleted(success: false)
                return
            }
            self?.handle(processingTask, coordinator: reference.coordinator)
        }
    }

    func schedule() {
        let request = BGProcessingTaskRequest(identifier: Self.identifier)
        request.requiresNetworkConnectivity = true
        request.requiresExternalPower = false
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    private func handle(_ task: BGProcessingTask, coordinator: UploadCoordinator) {
        let work = Task { () -> Bool in
            await coordinator.resumeCurrentUser()
        }
        task.expirationHandler = { work.cancel() }
        Task {
            let success = await work.value
            task.setTaskCompleted(success: success)
            if !success { schedule() }
        }
    }
}

private final class CoordinatorReference {
    let coordinator: UploadCoordinator

    init(coordinator: UploadCoordinator) {
        self.coordinator = coordinator
    }
}
