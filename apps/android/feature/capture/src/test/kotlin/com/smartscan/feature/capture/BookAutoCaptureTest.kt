package com.smartscan.feature.capture

import org.junit.Assert.assertEquals
import org.junit.Test

class BookAutoCaptureTest {
    private val ready = BookFrameSignals(0.0, true, true, 0.9, 0.1, 0.02)

    @Test
    fun `auto shutter requires a page turn and consecutive stable frames`() {
        var state = BookAutoCaptureState()
        repeat(5) { state = reduceBookAutoCapture(state, BookAutoCaptureEvent.FrameObserved(ready)) }
        assertEquals(BookAutoCapturePhase.WAIT_PAGE, state.phase)

        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.FrameObserved(ready.copy(motionScore = 0.2)))
        assertEquals(BookAutoCapturePhase.PAGE_CHANGED, state.phase)
        repeat(2) { state = reduceBookAutoCapture(state, BookAutoCaptureEvent.FrameObserved(ready)) }
        assertEquals(BookAutoCapturePhase.WAIT_STABLE, state.phase)
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.FrameObserved(ready))
        assertEquals(BookAutoCapturePhase.CAPTURE, state.phase)
    }

    @Test
    fun `layout focus exposure and occlusion each block automatic capture`() {
        val cases = listOf(
            ready.copy(focusReady = false) to BookAutoCaptureBlocker.NEEDS_FOCUS,
            ready.copy(exposureReady = false) to BookAutoCaptureBlocker.EXPOSURE_INVALID,
            ready.copy(boundaryConfidence = 0.2) to BookAutoCaptureBlocker.BOUNDARY_INCOMPLETE,
            ready.copy(spineConfidence = 0.0) to BookAutoCaptureBlocker.SPINE_NOT_FOUND,
            ready.copy(occlusionRatio = 0.5) to BookAutoCaptureBlocker.OCCLUSION_DETECTED,
        )
        for ((signals, blocker) in cases) {
            var state = reduceBookAutoCapture(
                BookAutoCaptureState(),
                BookAutoCaptureEvent.FrameObserved(ready.copy(motionScore = 0.2)),
            )
            repeat(3) { state = reduceBookAutoCapture(state, BookAutoCaptureEvent.FrameObserved(signals)) }
            assertEquals(blocker, state.blocker)
        }
    }

    @Test
    fun `accepted capture rearms only after another page turn and retry keeps current page`() {
        var state = BookAutoCaptureState(phase = BookAutoCapturePhase.CAPTURE, blocker = null, stableFrames = 3)
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.CaptureFinished)
        assertEquals(BookAutoCapturePhase.VERIFY, state.phase)
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.VerificationFinished(true))
        assertEquals(BookAutoCapturePhase.ACCEPT_OR_RETRY, state.phase)
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.ContinueAfterAccept)
        assertEquals(BookAutoCapturePhase.WAIT_PAGE, state.phase)

        state = BookAutoCaptureState(phase = BookAutoCapturePhase.VERIFY, blocker = BookAutoCaptureBlocker.VERIFYING)
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.VerificationFinished(false))
        state = reduceBookAutoCapture(state, BookAutoCaptureEvent.Retry)
        assertEquals(BookAutoCapturePhase.WAIT_STABLE, state.phase)
    }
}
