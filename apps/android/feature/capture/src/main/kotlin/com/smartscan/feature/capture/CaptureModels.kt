package com.smartscan.feature.capture

enum class CaptureMode(val routeValue: String) {
    DOCUMENT("document"),
    EXAM("exam"),
    BOOK("book");

    companion object {
        fun fromRoute(value: String?): CaptureMode = entries.firstOrNull { it.routeValue == value } ?: DOCUMENT
    }
}

enum class QualityIssue {
    ANALYZING,
    TOO_DARK,
    TOO_BRIGHT,
    BLURRY,
    GLARE,
}

data class FrameQuality(
    val brightness: Double,
    val sharpness: Double,
    val highlightRatio: Double,
    val issues: Set<QualityIssue>,
) {
    val ready: Boolean get() = issues.isEmpty()

    companion object {
        val Analyzing = FrameQuality(0.0, 0.0, 0.0, setOf(QualityIssue.ANALYZING))
    }
}

enum class CapturePhase {
    WAITING_PERMISSION,
    BINDING_CAMERA,
    READY,
    CAPTURING,
    CAPTURED,
    ERROR,
}

enum class CaptureError {
    PERMISSION_DENIED,
    CAMERA_UNAVAILABLE,
    SAVE_FAILED,
}

data class CaptureState(
    val phase: CapturePhase = CapturePhase.WAITING_PERMISSION,
    val quality: FrameQuality = FrameQuality.Analyzing,
    val originalPath: String? = null,
    val error: CaptureError? = null,
)

sealed interface CaptureEvent {
    data object PermissionGranted : CaptureEvent
    data object PermissionDenied : CaptureEvent
    data object CameraReady : CaptureEvent
    data object CameraFailed : CaptureEvent
    data class FrameAnalyzed(val quality: FrameQuality) : CaptureEvent
    data object ShutterPressed : CaptureEvent
    data class CaptureSucceeded(val originalPath: String) : CaptureEvent
    data object CaptureFailed : CaptureEvent
    data object ContinueCapturing : CaptureEvent
}

fun reduceCaptureState(state: CaptureState, event: CaptureEvent): CaptureState = when (event) {
    CaptureEvent.PermissionGranted -> state.copy(phase = CapturePhase.BINDING_CAMERA, error = null)
    CaptureEvent.PermissionDenied -> state.copy(phase = CapturePhase.ERROR, error = CaptureError.PERMISSION_DENIED)
    CaptureEvent.CameraReady -> state.copy(phase = CapturePhase.READY, error = null)
    CaptureEvent.CameraFailed -> state.copy(phase = CapturePhase.ERROR, error = CaptureError.CAMERA_UNAVAILABLE)
    is CaptureEvent.FrameAnalyzed -> if (state.phase == CapturePhase.READY) state.copy(quality = event.quality) else state
    CaptureEvent.ShutterPressed -> if (state.phase == CapturePhase.READY) state.copy(phase = CapturePhase.CAPTURING) else state
    is CaptureEvent.CaptureSucceeded -> if (state.phase == CapturePhase.CAPTURING) {
        state.copy(phase = CapturePhase.CAPTURED, originalPath = event.originalPath, error = null)
    } else {
        state
    }
    CaptureEvent.CaptureFailed -> if (state.phase == CapturePhase.CAPTURING) {
        state.copy(phase = CapturePhase.ERROR, error = CaptureError.SAVE_FAILED)
    } else {
        state
    }
    CaptureEvent.ContinueCapturing -> if (state.phase == CapturePhase.CAPTURED) {
        state.copy(phase = CapturePhase.READY, originalPath = null)
    } else {
        state
    }
}
