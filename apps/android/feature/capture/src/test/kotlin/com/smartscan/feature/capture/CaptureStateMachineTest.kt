package com.smartscan.feature.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CaptureStateMachineTest {
    @Test
    fun `permission camera and manual capture follow legal sequence`() {
        var state = CaptureState()
        state = reduceCaptureState(state, CaptureEvent.PermissionGranted)
        assertEquals(CapturePhase.BINDING_CAMERA, state.phase)

        state = reduceCaptureState(state, CaptureEvent.CameraReady)
        state = reduceCaptureState(state, CaptureEvent.ShutterPressed)
        assertEquals(CapturePhase.CAPTURING, state.phase)

        state = reduceCaptureState(state, CaptureEvent.CaptureSucceeded("/private/original.jpg"))
        assertEquals(CapturePhase.CAPTURED, state.phase)
        assertEquals("/private/original.jpg", state.originalPath)

        state = reduceCaptureState(state, CaptureEvent.ContinueCapturing)
        assertEquals(CapturePhase.READY, state.phase)
        assertNull(state.originalPath)
    }

    @Test
    fun `shutter is ignored before camera is ready`() {
        val state = reduceCaptureState(CaptureState(), CaptureEvent.ShutterPressed)

        assertEquals(CapturePhase.WAITING_PERMISSION, state.phase)
    }

    @Test
    fun `quality updates do not change state during capture`() {
        val quality = FrameQuality(0.5, 0.2, 0.0, emptySet())
        val capturing = CaptureState(phase = CapturePhase.CAPTURING)

        val updated = reduceCaptureState(capturing, CaptureEvent.FrameAnalyzed(quality))

        assertEquals(FrameQuality.Analyzing, updated.quality)
    }

    @Test
    fun `capture failure does not claim an original file`() {
        val capturing = CaptureState(phase = CapturePhase.CAPTURING)

        val failed = reduceCaptureState(capturing, CaptureEvent.CaptureFailed)

        assertEquals(CapturePhase.ERROR, failed.phase)
        assertEquals(CaptureError.SAVE_FAILED, failed.error)
        assertNull(failed.originalPath)

        val retried = reduceCaptureState(failed, CaptureEvent.Retry)
        assertEquals(CapturePhase.READY, retried.phase)
        assertNull(retried.error)
    }
}
