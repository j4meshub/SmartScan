import Foundation

enum BookAutoCapturePhase: String, Equatable, Sendable {
    case waitPage
    case pageChanged
    case waitStable
    case waitFocus
    case checkLayoutAndOcclusion
    case capture
    case verify
    case acceptOrRetry
}

enum BookAutoCaptureBlocker: String, Equatable, Sendable {
    case waitingForPageChange
    case pageMoving
    case needsFocus
    case exposureInvalid
    case boundaryIncomplete
    case spineNotFound
    case occlusionDetected
    case verifying
    case retryRequired
}

struct BookAutoCaptureThresholds: Equatable, Sendable {
    let minimumPageChangeScore: Double
    let maximumStableMotionScore: Double
    let stableFramesRequired: Int
    let minimumBoundaryConfidence: Double
    let minimumSpineConfidence: Double
    let maximumOcclusionRatio: Double

    init(
        minimumPageChangeScore: Double = 0.08,
        maximumStableMotionScore: Double = 0.025,
        stableFramesRequired: Int = 3,
        minimumBoundaryConfidence: Double = 0.6,
        minimumSpineConfidence: Double = 0.035,
        maximumOcclusionRatio: Double = 0.2
    ) {
        precondition((0 ... 1).contains(minimumPageChangeScore))
        precondition((0 ... minimumPageChangeScore).contains(maximumStableMotionScore))
        precondition(stableFramesRequired > 0)
        precondition((0 ... 1).contains(minimumBoundaryConfidence))
        precondition((0 ... 1).contains(minimumSpineConfidence))
        precondition((0 ... 1).contains(maximumOcclusionRatio))
        self.minimumPageChangeScore = minimumPageChangeScore
        self.maximumStableMotionScore = maximumStableMotionScore
        self.stableFramesRequired = stableFramesRequired
        self.minimumBoundaryConfidence = minimumBoundaryConfidence
        self.minimumSpineConfidence = minimumSpineConfidence
        self.maximumOcclusionRatio = maximumOcclusionRatio
    }
}

struct BookFrameSignals: Equatable, Sendable {
    let motionScore: Double
    let focusReady: Bool
    let exposureReady: Bool
    let boundaryConfidence: Double
    let spineConfidence: Double
    let occlusionRatio: Double
}

struct BookAutoCaptureState: Equatable, Sendable {
    var phase: BookAutoCapturePhase = .waitPage
    var blocker: BookAutoCaptureBlocker? = .waitingForPageChange
    var stableFrames = 0
    var accepted: Bool?
}

enum BookAutoCaptureEvent: Equatable, Sendable {
    case frameObserved(BookFrameSignals)
    case captureFinished
    case verificationFinished(Bool)
    case continueAfterAccept
    case retry
    case reset
}

func reduceBookAutoCapture(
    _ state: BookAutoCaptureState,
    event: BookAutoCaptureEvent,
    thresholds: BookAutoCaptureThresholds = BookAutoCaptureThresholds()
) -> BookAutoCaptureState {
    switch event {
    case let .frameObserved(signals):
        return reduceBookFrame(state, signals: signals, thresholds: thresholds)
    case .captureFinished:
        return state.phase == .capture
            ? BookAutoCaptureState(phase: .verify, blocker: .verifying, stableFrames: state.stableFrames)
            : state
    case let .verificationFinished(accepted):
        return state.phase == .verify
            ? BookAutoCaptureState(
                phase: .acceptOrRetry,
                blocker: accepted ? nil : .retryRequired,
                stableFrames: state.stableFrames,
                accepted: accepted
            )
            : state
    case .continueAfterAccept:
        return state.phase == .acceptOrRetry && state.accepted == true ? BookAutoCaptureState() : state
    case .retry:
        return state.phase == .acceptOrRetry && state.accepted == false
            ? BookAutoCaptureState(phase: .waitStable, blocker: .pageMoving)
            : state
    case .reset:
        return BookAutoCaptureState()
    }
}

private func reduceBookFrame(
    _ state: BookAutoCaptureState,
    signals: BookFrameSignals,
    thresholds: BookAutoCaptureThresholds
) -> BookAutoCaptureState {
    guard ![.capture, .verify, .acceptOrRetry].contains(state.phase) else { return state }
    if state.phase == .waitPage {
        return signals.motionScore >= thresholds.minimumPageChangeScore
            ? BookAutoCaptureState(phase: .pageChanged, blocker: nil)
            : state
    }
    if signals.motionScore >= thresholds.minimumPageChangeScore {
        return BookAutoCaptureState(phase: .pageChanged, blocker: nil)
    }
    if signals.motionScore > thresholds.maximumStableMotionScore {
        return BookAutoCaptureState(phase: .waitStable, blocker: .pageMoving)
    }
    let stableFrames = state.stableFrames + 1
    if stableFrames < thresholds.stableFramesRequired {
        return BookAutoCaptureState(phase: .waitStable, blocker: .pageMoving, stableFrames: stableFrames)
    }
    if !signals.focusReady {
        return BookAutoCaptureState(phase: .waitFocus, blocker: .needsFocus, stableFrames: stableFrames)
    }
    if !signals.exposureReady {
        return BookAutoCaptureState(phase: .waitFocus, blocker: .exposureInvalid, stableFrames: stableFrames)
    }
    let blocker: BookAutoCaptureBlocker?
    if signals.boundaryConfidence < thresholds.minimumBoundaryConfidence {
        blocker = .boundaryIncomplete
    } else if signals.spineConfidence < thresholds.minimumSpineConfidence {
        blocker = .spineNotFound
    } else if signals.occlusionRatio > thresholds.maximumOcclusionRatio {
        blocker = .occlusionDetected
    } else {
        blocker = nil
    }
    return BookAutoCaptureState(
        phase: blocker == nil ? .capture : .checkLayoutAndOcclusion,
        blocker: blocker,
        stableFrames: stableFrames
    )
}

extension FrameQuality {
    var bookSignals: BookFrameSignals {
        BookFrameSignals(
            motionScore: motionScore ?? 0,
            focusReady: !issues.contains(.blurry) && !issues.contains(.analyzing),
            exposureReady: issues.isDisjoint(with: [.tooDark, .tooBright, .glare]),
            boundaryConfidence: boundaryConfidence ?? rectangleConfidence ?? 0,
            spineConfidence: spineConfidence ?? 0,
            occlusionRatio: occlusionRatio ?? 1
        )
    }
}
