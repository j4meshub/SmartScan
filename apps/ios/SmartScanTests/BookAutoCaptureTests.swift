@testable import SmartScan
import XCTest

final class BookAutoCaptureTests: XCTestCase {
    private let ready = BookFrameSignals(
        motionScore: 0,
        focusReady: true,
        exposureReady: true,
        boundaryConfidence: 0.9,
        spineConfidence: 0.1,
        occlusionRatio: 0.02
    )

    func testPageTurnAndConsecutiveStableFramesAreRequired() {
        var state = BookAutoCaptureState()
        for _ in 0 ..< 5 { state = reduceBookAutoCapture(state, event: .frameObserved(ready)) }
        XCTAssertEqual(state.phase, .waitPage)

        state = reduceBookAutoCapture(state, event: .frameObserved(changed(ready, motion: 0.2)))
        XCTAssertEqual(state.phase, .pageChanged)
        for _ in 0 ..< 2 { state = reduceBookAutoCapture(state, event: .frameObserved(ready)) }
        XCTAssertEqual(state.phase, .waitStable)
        state = reduceBookAutoCapture(state, event: .frameObserved(ready))
        XCTAssertEqual(state.phase, .capture)
    }

    func testEverySafetySignalCanBlockCapture() {
        let cases: [(BookFrameSignals, BookAutoCaptureBlocker)] = [
            (BookFrameSignals(motionScore: 0, focusReady: false, exposureReady: true, boundaryConfidence: 0.9, spineConfidence: 0.1, occlusionRatio: 0.02), .needsFocus),
            (BookFrameSignals(motionScore: 0, focusReady: true, exposureReady: false, boundaryConfidence: 0.9, spineConfidence: 0.1, occlusionRatio: 0.02), .exposureInvalid),
            (BookFrameSignals(motionScore: 0, focusReady: true, exposureReady: true, boundaryConfidence: 0.2, spineConfidence: 0.1, occlusionRatio: 0.02), .boundaryIncomplete),
            (BookFrameSignals(motionScore: 0, focusReady: true, exposureReady: true, boundaryConfidence: 0.9, spineConfidence: 0, occlusionRatio: 0.02), .spineNotFound),
            (BookFrameSignals(motionScore: 0, focusReady: true, exposureReady: true, boundaryConfidence: 0.9, spineConfidence: 0.1, occlusionRatio: 0.5), .occlusionDetected),
        ]
        for (signals, blocker) in cases {
            var state = reduceBookAutoCapture(BookAutoCaptureState(), event: .frameObserved(changed(ready, motion: 0.2)))
            for _ in 0 ..< 3 { state = reduceBookAutoCapture(state, event: .frameObserved(signals)) }
            XCTAssertEqual(state.blocker, blocker)
        }
    }

    func testAcceptedCaptureRearmsAndFailedVerificationRetriesCurrentPage() {
        var state = BookAutoCaptureState(phase: .capture, blocker: nil, stableFrames: 3)
        state = reduceBookAutoCapture(state, event: .captureFinished)
        XCTAssertEqual(state.phase, .verify)
        state = reduceBookAutoCapture(state, event: .verificationFinished(true))
        state = reduceBookAutoCapture(state, event: .continueAfterAccept)
        XCTAssertEqual(state.phase, .waitPage)

        state = BookAutoCaptureState(phase: .verify, blocker: .verifying)
        state = reduceBookAutoCapture(state, event: .verificationFinished(false))
        state = reduceBookAutoCapture(state, event: .retry)
        XCTAssertEqual(state.phase, .waitStable)
    }

    private func changed(_ signals: BookFrameSignals, motion: Double) -> BookFrameSignals {
        BookFrameSignals(
            motionScore: motion,
            focusReady: signals.focusReady,
            exposureReady: signals.exposureReady,
            boundaryConfidence: signals.boundaryConfidence,
            spineConfidence: signals.spineConfidence,
            occlusionRatio: signals.occlusionRatio
        )
    }
}
