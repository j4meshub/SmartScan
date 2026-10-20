export class CameraUnavailableError extends Error {
  constructor(code, cause) {
    super(code, {cause});
    this.name = "CameraUnavailableError";
    this.code = code;
  }
}

export function cameraCapabilities({mediaDevices, imageCaptureCtor} = {}) {
  return {
    realtimeCamera: typeof mediaDevices?.getUserMedia === "function",
    imageCapture: typeof imageCaptureCtor === "function",
    systemCaptureFallback: true,
  };
}

export async function openEnvironmentCamera({mediaDevices, videoElement}) {
  if (typeof mediaDevices?.getUserMedia !== "function") {
    throw new CameraUnavailableError("camera_not_supported");
  }
  let stream;
  try {
    stream = await mediaDevices.getUserMedia({
      audio: false,
      video: {facingMode: {ideal: "environment"}},
    });
    videoElement.srcObject = stream;
    videoElement.setAttribute("playsinline", "");
    await videoElement.play();
    return stream;
  } catch (error) {
    stopCamera(stream);
    if (videoElement) videoElement.srcObject = null;
    throw new CameraUnavailableError("camera_open_failed", error);
  }
}

export async function captureCameraPhoto({
  stream,
  videoElement,
  imageCaptureCtor,
  canvasFactory = () => document.createElement("canvas"),
}) {
  const track = stream?.getVideoTracks?.()[0];
  if (!track) throw new CameraUnavailableError("camera_track_missing");
  if (typeof imageCaptureCtor === "function") {
    try {
      return await new imageCaptureCtor(track).takePhoto();
    } catch (error) {
      throw new CameraUnavailableError("camera_capture_failed", error);
    }
  }

  if (!videoElement?.videoWidth || !videoElement?.videoHeight) {
    throw new CameraUnavailableError("camera_frame_unavailable");
  }
  const canvas = canvasFactory();
  canvas.width = videoElement.videoWidth;
  canvas.height = videoElement.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new CameraUnavailableError("camera_canvas_unavailable");
  context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      blob => blob ? resolve(blob) : reject(new CameraUnavailableError("camera_capture_failed")),
      "image/jpeg",
      0.92,
    );
  });
}

export function stopCamera(stream) {
  for (const track of stream?.getTracks?.() || []) track.stop();
}

export function cameraBlobToFile(blob, timestamp = Date.now()) {
  const extension = blob.type === "image/png" ? "png" : "jpg";
  return new File([blob], `camera_${timestamp}.${extension}`, {
    type: blob.type || "image/jpeg",
    lastModified: timestamp,
  });
}
