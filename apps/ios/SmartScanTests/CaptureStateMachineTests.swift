@testable import SmartScan
import Foundation
import XCTest

final class CaptureStateMachineTests: XCTestCase {
    func testPermissionCameraAndManualCaptureFollowLegalSequence() {
        var state = CaptureState()
        state = reduceCaptureState(state, event: .permissionGranted)
        XCTAssertEqual(state.phase, .bindingCamera)

        state = reduceCaptureState(state, event: .cameraReady)
        state = reduceCaptureState(state, event: .shutterPressed)
        XCTAssertEqual(state.phase, .capturing)

        let record = CaptureRecord(
            id: "capture-1",
            originalURL: URL(fileURLWithPath: "/private/original.jpg"),
            evidenceURL: URL(fileURLWithPath: "/private/evidence.json")
        )
        state = reduceCaptureState(state, event: .captureSucceeded(record))
        XCTAssertEqual(state.phase, .captured(record))

        state = reduceCaptureState(state, event: .continueCapturing)
        XCTAssertEqual(state.phase, .ready)
        XCTAssertEqual(state.quality, .analyzing)
    }

    func testShutterIsIgnoredBeforeCameraIsReady() {
        XCTAssertEqual(reduceCaptureState(CaptureState(), event: .shutterPressed), CaptureState())
    }

    func testQualityDoesNotChangeWhileCapturing() {
        let quality = FrameQuality(
            brightness: 0.5,
            sharpness: 0.2,
            highlightRatio: 0,
            rectangleConfidence: 0.9,
            issues: []
        )
        let state = CaptureState(phase: .capturing)

        XCTAssertEqual(reduceCaptureState(state, event: .frameAnalyzed(quality, nil)), state)
    }

    func testSaveFailureCanReturnToReadyWithoutRebindingCamera() {
        var state = CaptureState(phase: .capturing)
        state = reduceCaptureState(state, event: .captureFailed)
        XCTAssertEqual(state.phase, .failed(.saveFailed))

        state = reduceCaptureState(state, event: .retry)
        XCTAssertEqual(state.phase, .ready)
    }
}
