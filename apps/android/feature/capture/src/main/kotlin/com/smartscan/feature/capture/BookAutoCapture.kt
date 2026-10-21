package com.smartscan.feature.capture

enum class BookAutoCapturePhase {
    WAIT_PAGE,
    PAGE_CHANGED,
    WAIT_STABLE,
    WAIT_FOCUS,
    CHECK_LAYOUT_AND_OCCLUSION,
    CAPTURE,
    VERIFY,
    ACCEPT_OR_RETRY,
}

enum class BookAutoCaptureBlocker {
    WAITING_FOR_PAGE_CHANGE,
    PAGE_MOVING,
    NEEDS_FOCUS,
    EXPOSURE_INVALID,
    BOUNDARY_INCOMPLETE,
    SPINE_NOT_FOUND,
    OCCLUSION_DETECTED,
    VERIFYING,
    RETRY_REQUIRED,
}

data class BookAutoCaptureThresholds(
    val minimumPageChangeScore: Double = 0.08,
    val maximumStableMotionScore: Double = 0.025,
    val stableFramesRequired: Int = 3,
    val minimumBoundaryConfidence: Double = 0.6,
    val minimumSpineConfidence: Double = 0.035,
    val maximumOcclusionRatio: Double = 0.2,
) {
    init {
        require(minimumPageChangeScore in 0.0..1.0)
        require(maximumStableMotionScore in 0.0..minimumPageChangeScore)
        require(stableFramesRequired > 0)
        require(minimumBoundaryConfidence in 0.0..1.0)
        require(minimumSpineConfidence in 0.0..1.0)
        require(maximumOcclusionRatio in 0.0..1.0)
    }
}

data class BookFrameSignals(
    val motionScore: Double,
    val focusReady: Boolean,
    val exposureReady: Boolean,
    val boundaryConfidence: Double,
    val spineConfidence: Double,
    val occlusionRatio: Double,
)

data class BookAutoCaptureState(
    val phase: BookAutoCapturePhase = BookAutoCapturePhase.WAIT_PAGE,
    val blocker: BookAutoCaptureBlocker? = BookAutoCaptureBlocker.WAITING_FOR_PAGE_CHANGE,
    val stableFrames: Int = 0,
    val accepted: Boolean? = null,
)

sealed interface BookAutoCaptureEvent {
    data class FrameObserved(val signals: BookFrameSignals) : BookAutoCaptureEvent
    data object CaptureFinished : BookAutoCaptureEvent
    data class VerificationFinished(val accepted: Boolean) : BookAutoCaptureEvent
    data object ContinueAfterAccept : BookAutoCaptureEvent
    data object Retry : BookAutoCaptureEvent
    data object Reset : BookAutoCaptureEvent
}

fun reduceBookAutoCapture(
    state: BookAutoCaptureState,
    event: BookAutoCaptureEvent,
    thresholds: BookAutoCaptureThresholds = BookAutoCaptureThresholds(),
): BookAutoCaptureState = when (event) {
    is BookAutoCaptureEvent.FrameObserved -> reduceBookFrame(state, event.signals, thresholds)
    BookAutoCaptureEvent.CaptureFinished -> if (state.phase == BookAutoCapturePhase.CAPTURE) {
        state.copy(
            phase = BookAutoCapturePhase.VERIFY,
            blocker = BookAutoCaptureBlocker.VERIFYING,
            accepted = null,
        )
    } else {
        state
    }
    is BookAutoCaptureEvent.VerificationFinished -> if (state.phase == BookAutoCapturePhase.VERIFY) {
        state.copy(
            phase = BookAutoCapturePhase.ACCEPT_OR_RETRY,
            blocker = if (event.accepted) null else BookAutoCaptureBlocker.RETRY_REQUIRED,
            accepted = event.accepted,
        )
    } else {
        state
    }
    BookAutoCaptureEvent.ContinueAfterAccept -> if (
        state.phase == BookAutoCapturePhase.ACCEPT_OR_RETRY && state.accepted == true
    ) {
        BookAutoCaptureState()
    } else {
        state
    }
    BookAutoCaptureEvent.Retry -> if (
        state.phase == BookAutoCapturePhase.ACCEPT_OR_RETRY && state.accepted == false
    ) {
        BookAutoCaptureState(
            phase = BookAutoCapturePhase.WAIT_STABLE,
            blocker = BookAutoCaptureBlocker.PAGE_MOVING,
        )
    } else {
        state
    }
    BookAutoCaptureEvent.Reset -> BookAutoCaptureState()
}

private fun reduceBookFrame(
    state: BookAutoCaptureState,
    signals: BookFrameSignals,
    thresholds: BookAutoCaptureThresholds,
): BookAutoCaptureState {
    if (state.phase in setOf(
            BookAutoCapturePhase.CAPTURE,
            BookAutoCapturePhase.VERIFY,
            BookAutoCapturePhase.ACCEPT_OR_RETRY,
        )
    ) return state

    if (state.phase == BookAutoCapturePhase.WAIT_PAGE) {
        return if (signals.motionScore >= thresholds.minimumPageChangeScore) {
            BookAutoCaptureState(phase = BookAutoCapturePhase.PAGE_CHANGED, blocker = null)
        } else {
            state
        }
    }
    if (signals.motionScore >= thresholds.minimumPageChangeScore) {
        return BookAutoCaptureState(phase = BookAutoCapturePhase.PAGE_CHANGED, blocker = null)
    }
    if (signals.motionScore > thresholds.maximumStableMotionScore) {
        return BookAutoCaptureState(
            phase = BookAutoCapturePhase.WAIT_STABLE,
            blocker = BookAutoCaptureBlocker.PAGE_MOVING,
        )
    }

    val stableFrames = state.stableFrames + 1
    if (stableFrames < thresholds.stableFramesRequired) {
        return state.copy(
            phase = BookAutoCapturePhase.WAIT_STABLE,
            blocker = BookAutoCaptureBlocker.PAGE_MOVING,
            stableFrames = stableFrames,
        )
    }
    if (!signals.focusReady) {
        return state.copy(
            phase = BookAutoCapturePhase.WAIT_FOCUS,
            blocker = BookAutoCaptureBlocker.NEEDS_FOCUS,
            stableFrames = stableFrames,
        )
    }
    if (!signals.exposureReady) {
        return state.copy(
            phase = BookAutoCapturePhase.WAIT_FOCUS,
            blocker = BookAutoCaptureBlocker.EXPOSURE_INVALID,
            stableFrames = stableFrames,
        )
    }
    val layoutBlocker = when {
        signals.boundaryConfidence < thresholds.minimumBoundaryConfidence -> BookAutoCaptureBlocker.BOUNDARY_INCOMPLETE
        signals.spineConfidence < thresholds.minimumSpineConfidence -> BookAutoCaptureBlocker.SPINE_NOT_FOUND
        signals.occlusionRatio > thresholds.maximumOcclusionRatio -> BookAutoCaptureBlocker.OCCLUSION_DETECTED
        else -> null
    }
    return if (layoutBlocker == null) {
        state.copy(
            phase = BookAutoCapturePhase.CAPTURE,
            blocker = null,
            stableFrames = stableFrames,
        )
    } else {
        state.copy(
            phase = BookAutoCapturePhase.CHECK_LAYOUT_AND_OCCLUSION,
            blocker = layoutBlocker,
            stableFrames = stableFrames,
        )
    }
}

fun FrameQuality.bookSignals(): BookFrameSignals = BookFrameSignals(
    motionScore = motionScore,
    focusReady = QualityIssue.BLURRY !in issues && QualityIssue.ANALYZING !in issues,
    exposureReady = issues.none { it in setOf(QualityIssue.TOO_DARK, QualityIssue.TOO_BRIGHT, QualityIssue.GLARE) },
    boundaryConfidence = boundaryConfidence,
    spineConfidence = spineConfidence,
    occlusionRatio = occlusionRatio,
)
