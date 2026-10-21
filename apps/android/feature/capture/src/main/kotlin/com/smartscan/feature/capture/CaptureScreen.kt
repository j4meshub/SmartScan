package com.smartscan.feature.capture

import android.Manifest
import android.content.pm.PackageManager
import android.os.SystemClock
import android.view.Surface as AndroidSurface
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val Overlay = Color(0xB3111827)
private val ReadyGreen = Color(0xFFB7F7D4)

@Composable
fun CaptureScreen(
    mode: CaptureMode,
    onBack: () -> Unit,
    onOriginalCaptured: suspend (String) -> Boolean = { true },
) {
    val context = LocalContext.current
    val mainExecutor = remember(context) { ContextCompat.getMainExecutor(context) }
    var state by remember { mutableStateOf(CaptureState()) }
    var hasPermission by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var session by remember { mutableStateOf<CameraSession?>(null) }
    var exposureIndex by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasPermission = granted
        state = reduceCaptureState(state, if (granted) CaptureEvent.PermissionGranted else CaptureEvent.PermissionDenied)
    }

    LaunchedEffect(Unit) {
        if (hasPermission) {
            state = reduceCaptureState(state, CaptureEvent.PermissionGranted)
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (hasPermission) {
            CameraPreview(
                onCameraReady = { readySession ->
                    session = readySession
                    exposureIndex = readySession.camera.cameraInfo.exposureState.exposureCompensationIndex
                    state = reduceCaptureState(state, CaptureEvent.CameraReady)
                },
                onQuality = { quality -> state = reduceCaptureState(state, CaptureEvent.FrameAnalyzed(quality)) },
                onCameraFailed = { state = reduceCaptureState(state, CaptureEvent.CameraFailed) },
                modifier = Modifier.fillMaxSize(),
            )
            session?.let { current ->
                Box(
                    Modifier.fillMaxSize().pointerInput(current) {
                        detectTapGestures { offset -> current.focus(offset.x, offset.y) }
                    },
                )
            }
        }

        CaptureTopBar(mode, onBack, Modifier.align(Alignment.TopCenter))

        when {
            !hasPermission || state.error == CaptureError.PERMISSION_DENIED -> PermissionPanel(
                onRetry = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                modifier = Modifier.align(Alignment.Center),
            )
            state.error == CaptureError.CAMERA_UNAVAILABLE -> ErrorPanel(
                message = stringResource(R.string.capture_camera_unavailable),
                modifier = Modifier.align(Alignment.Center),
            )
            state.phase == CapturePhase.CAPTURED -> CapturedPanel(
                onContinue = { state = reduceCaptureState(state, CaptureEvent.ContinueCapturing) },
                modifier = Modifier.align(Alignment.Center),
            )
            state.error == CaptureError.SAVE_FAILED -> ErrorPanel(
                message = stringResource(R.string.capture_save_failed),
                modifier = Modifier.align(Alignment.Center),
            )
            else -> CaptureControls(
                state = state,
                exposureIndex = exposureIndex,
                onExposureChange = { delta ->
                    session?.let { current ->
                        val range = current.camera.cameraInfo.exposureState.exposureCompensationRange
                        val target = (exposureIndex + delta).coerceIn(range.lower, range.upper)
                        exposureIndex = target
                        current.camera.cameraControl.setExposureCompensationIndex(target)
                    }
                },
                onShutter = shutter@{
                    val current = session ?: return@shutter
                    state = reduceCaptureState(state, CaptureEvent.ShutterPressed)
                    val directory = File(context.filesDir, "captures/originals")
                    if ((!directory.exists() && !directory.mkdirs()) || !directory.isDirectory) {
                        state = reduceCaptureState(state, CaptureEvent.CaptureFailed)
                        return@shutter
                    }
                    val output = File(directory, "original_${System.currentTimeMillis()}_${UUID.randomUUID()}.jpg")
                    current.imageCapture.takePicture(
                        ImageCapture.OutputFileOptions.Builder(output).build(),
                        mainExecutor,
                        object : ImageCapture.OnImageSavedCallback {
                            override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                                scope.launch {
                                    val accepted = withContext(NonCancellable) {
                                        runCatching { onOriginalCaptured(output.absolutePath) }.getOrDefault(false)
                                    }
                                    if (accepted) {
                                        state = reduceCaptureState(state, CaptureEvent.CaptureSucceeded(output.absolutePath))
                                    } else {
                                        output.delete()
                                        state = reduceCaptureState(state, CaptureEvent.CaptureFailed)
                                    }
                                }
                            }

                            override fun onError(exception: ImageCaptureException) {
                                output.delete()
                                state = reduceCaptureState(state, CaptureEvent.CaptureFailed)
                            }
                        },
                    )
                },
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

@Composable
private fun CaptureTopBar(mode: CaptureMode, onBack: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().background(Overlay).padding(horizontal = 12.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = onBack) { Text(stringResource(R.string.capture_back), color = Color.White) }
        Text(
            text = stringResource(
                when (mode) {
                    CaptureMode.DOCUMENT -> R.string.capture_mode_document
                    CaptureMode.EXAM -> R.string.capture_mode_exam
                    CaptureMode.BOOK -> R.string.capture_mode_book
                },
            ),
            color = Color.White,
            style = MaterialTheme.typography.titleMedium,
        )
    }
}

@Composable
private fun CaptureControls(
    state: CaptureState,
    exposureIndex: Int,
    onExposureChange: (Int) -> Unit,
    onShutter: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth().background(Overlay).padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        QualityMessage(state.quality)
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.capture_exposure), color = Color.White)
            IconButton(onClick = { onExposureChange(-1) }) { Text("−", color = Color.White, fontSize = 24.sp) }
            Text(exposureIndex.toString(), color = Color.White)
            IconButton(onClick = { onExposureChange(1) }) { Text("+", color = Color.White, fontSize = 24.sp) }
        }
        Button(
            onClick = onShutter,
            enabled = state.phase == CapturePhase.READY,
            modifier = Modifier.size(78.dp),
            shape = CircleShape,
            colors = ButtonDefaults.buttonColors(containerColor = Color.White, disabledContainerColor = Color.Gray),
        ) { Text("", modifier = Modifier.size(48.dp).background(Color(0xFF111827), CircleShape)) }
        Text(stringResource(R.string.capture_manual_hint), color = Color.White, fontSize = 12.sp)
    }
}

@Composable
private fun QualityMessage(quality: FrameQuality) {
    val message = when {
        QualityIssue.ANALYZING in quality.issues -> stringResource(R.string.capture_quality_analyzing)
        quality.ready -> stringResource(R.string.capture_quality_ready)
        QualityIssue.TOO_DARK in quality.issues -> stringResource(R.string.capture_quality_dark)
        QualityIssue.TOO_BRIGHT in quality.issues -> stringResource(R.string.capture_quality_bright)
        QualityIssue.GLARE in quality.issues -> stringResource(R.string.capture_quality_glare)
        else -> stringResource(R.string.capture_quality_blurry)
    }
    Surface(color = if (quality.ready) ReadyGreen else Color(0xFFFFE0A3), shape = RoundedCornerShape(20.dp)) {
        Text(message, Modifier.padding(horizontal = 14.dp, vertical = 8.dp), color = Color(0xFF111827))
    }
}

@Composable
private fun PermissionPanel(onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Surface(modifier = modifier.padding(24.dp), color = Overlay, shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.capture_permission_required), color = Color.White)
            Spacer(Modifier.height(12.dp))
            Button(onClick = onRetry) { Text(stringResource(R.string.capture_permission_action)) }
        }
    }
}

@Composable
private fun ErrorPanel(message: String, modifier: Modifier = Modifier) {
    Surface(modifier = modifier.padding(24.dp), color = Overlay, shape = RoundedCornerShape(20.dp)) {
        Text(message, Modifier.padding(24.dp), color = Color.White)
    }
}

@Composable
private fun CapturedPanel(onContinue: () -> Unit, modifier: Modifier = Modifier) {
    Surface(modifier = modifier.padding(24.dp), color = Overlay, shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.capture_saved_original), color = Color.White)
            Spacer(Modifier.height(12.dp))
            Button(onClick = onContinue) { Text(stringResource(R.string.capture_continue)) }
        }
    }
}

private data class CameraSession(
    val imageCapture: ImageCapture,
    val camera: Camera,
    val previewView: PreviewView,
) {
    fun focus(x: Float, y: Float) {
        val point = previewView.meteringPointFactory.createPoint(x, y)
        val action = FocusMeteringAction.Builder(
            point,
            FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE,
        ).setAutoCancelDuration(3, TimeUnit.SECONDS).build()
        camera.cameraControl.startFocusAndMetering(action)
    }
}

@Composable
private fun CameraPreview(
    onCameraReady: (CameraSession) -> Unit,
    onQuality: (FrameQuality) -> Unit,
    onCameraFailed: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val mainExecutor = remember(context) { ContextCompat.getMainExecutor(context) }
    val analyzerExecutor = remember { Executors.newSingleThreadExecutor() }
    val providerReference = remember { AtomicReference<ProcessCameraProvider?>() }
    val disposed = remember { AtomicBoolean(false) }
    val evaluator = remember { FrameQualityEvaluator() }

    AndroidView(
        modifier = modifier,
        factory = { viewContext ->
            PreviewView(viewContext).apply {
                implementationMode = PreviewView.ImplementationMode.COMPATIBLE
                scaleType = PreviewView.ScaleType.FILL_CENTER
                val previewView = this
                val providerFuture = ProcessCameraProvider.getInstance(viewContext)
                providerFuture.addListener({
                    if (disposed.get()) return@addListener
                    try {
                        val provider = providerFuture.get()
                        providerReference.set(provider)
                        val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
                        val imageCapture = ImageCapture.Builder()
                            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                            .setTargetRotation(AndroidSurface.ROTATION_0)
                            .build()
                        var lastAnalysisAt = 0L
                        val analysis = ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build()
                            .also { useCase ->
                                useCase.setAnalyzer(analyzerExecutor) { image ->
                                    val now = SystemClock.elapsedRealtime()
                                    if (now - lastAnalysisAt >= 250) {
                                        lastAnalysisAt = now
                                        analyzeFrame(image, evaluator)?.let { quality ->
                                            mainExecutor.execute { if (!disposed.get()) onQuality(quality) }
                                        }
                                    }
                                    image.close()
                                }
                            }
                        provider.unbindAll()
                        val camera = provider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            imageCapture,
                            analysis,
                        )
                        onCameraReady(CameraSession(imageCapture, camera, previewView))
                    } catch (_: Exception) {
                        onCameraFailed()
                    }
                }, mainExecutor)
            }
        },
    )

    DisposableEffect(Unit) {
        onDispose {
            disposed.set(true)
            providerReference.get()?.unbindAll()
            analyzerExecutor.shutdownNow()
        }
    }
}

private fun analyzeFrame(image: ImageProxy, evaluator: FrameQualityEvaluator): FrameQuality? = runCatching {
    val plane = image.planes.first()
    val buffer = plane.buffer
    val bytes = ByteArray(buffer.remaining())
    buffer.get(bytes)
    evaluator.evaluate(
        luma = bytes,
        width = image.width,
        height = image.height,
        rowStride = plane.rowStride,
        pixelStride = plane.pixelStride,
    )
}.getOrNull()
