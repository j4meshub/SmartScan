export const initialBookAutoCaptureState = () => ({
  phase: "WAIT_PAGE",
  blocker: "waiting_for_page_change",
  stableFrames: 0,
  accepted: null,
});

export const defaultBookAutoThresholds = Object.freeze({
  minimumPageChangeScore: 0.08,
  maximumStableMotionScore: 0.025,
  stableFramesRequired: 3,
  minimumBoundaryConfidence: 0.6,
  minimumSpineConfidence: 0.035,
  maximumOcclusionRatio: 0.2,
});

export function reduceBookAutoCapture(state, event, thresholds = defaultBookAutoThresholds) {
  if (event.type === "reset") return initialBookAutoCaptureState();
  if (event.type === "capture_finished") {
    return state.phase === "CAPTURE" ? {...state, phase: "VERIFY", blocker: "verifying"} : state;
  }
  if (event.type === "verification_finished") {
    return state.phase === "VERIFY"
      ? {...state, phase: "ACCEPT_OR_RETRY", blocker: event.accepted ? null : "retry_required", accepted: event.accepted}
      : state;
  }
  if (event.type === "continue_after_accept") {
    return state.phase === "ACCEPT_OR_RETRY" && state.accepted ? initialBookAutoCaptureState() : state;
  }
  if (event.type !== "frame") return state;
  if (["CAPTURE", "VERIFY", "ACCEPT_OR_RETRY"].includes(state.phase)) return state;
  const signals = event.signals;
  if (state.phase === "WAIT_PAGE") {
    return signals.motionScore >= thresholds.minimumPageChangeScore
      ? {phase: "PAGE_CHANGED", blocker: null, stableFrames: 0, accepted: null}
      : state;
  }
  if (signals.motionScore >= thresholds.minimumPageChangeScore) {
    return {phase: "PAGE_CHANGED", blocker: null, stableFrames: 0, accepted: null};
  }
  if (signals.motionScore > thresholds.maximumStableMotionScore) {
    return {phase: "WAIT_STABLE", blocker: "page_moving", stableFrames: 0, accepted: null};
  }
  const stableFrames = state.stableFrames + 1;
  if (stableFrames < thresholds.stableFramesRequired) {
    return {...state, phase: "WAIT_STABLE", blocker: "page_moving", stableFrames};
  }
  if (!signals.focusReady) return {...state, phase: "WAIT_FOCUS", blocker: "needs_focus", stableFrames};
  if (!signals.exposureReady) return {...state, phase: "WAIT_FOCUS", blocker: "exposure_invalid", stableFrames};
  const blocker = signals.boundaryConfidence < thresholds.minimumBoundaryConfidence ? "boundary_incomplete"
    : signals.spineConfidence < thresholds.minimumSpineConfidence ? "spine_not_found"
      : signals.occlusionRatio > thresholds.maximumOcclusionRatio ? "occlusion_detected" : null;
  return {...state, phase: blocker ? "CHECK_LAYOUT_AND_OCCLUSION" : "CAPTURE", blocker, stableFrames};
}

export function analyzeBookLuma(luma, width, height, previousLuma = null) {
  if (!(luma instanceof Uint8Array) || width < 2 || height < 2 || luma.length !== width * height) {
    throw new TypeError("book_frame_invalid");
  }
  const motionScore = previousLuma?.length === luma.length
    ? luma.reduce((sum, value, index) => sum + Math.abs(value - previousLuma[index]), 0) / luma.length / 255
    : 0;
  const mean = (x0, x1, y0, y1) => {
    let total = 0, count = 0;
    const startY = Math.min(height - 1, Math.max(0, Math.floor(height * y0)));
    const endY = Math.min(height, Math.max(startY + 1, Math.floor(height * y1)));
    const startX = Math.min(width - 1, Math.max(0, Math.floor(width * x0)));
    const endX = Math.min(width, Math.max(startX + 1, Math.floor(width * x1)));
    for (let y = startY; y < endY; y += 2) {
      for (let x = startX; x < endX; x += 2) {
        total += luma[y * width + x]; count += 1;
      }
    }
    return count ? total / count : 0;
  };
  const boundaryContrasts = [
    Math.abs(mean(0, .08, .1, .9) - mean(.15, .3, .1, .9)),
    Math.abs(mean(.92, 1, .1, .9) - mean(.7, .85, .1, .9)),
    Math.abs(mean(.1, .9, 0, .08) - mean(.1, .9, .15, .3)),
    Math.abs(mean(.1, .9, .92, 1) - mean(.1, .9, .7, .85)),
  ];
  const boundaryConfidence = boundaryContrasts.filter(value => value >= 9).length / 4;
  const sideMean = (mean(.2, .4, .15, .85) + mean(.6, .8, .15, .85)) / 2;
  const centerMean = mean(.47, .53, .15, .85);
  const spineConfidence = Math.max(0, Math.min(1, (sideMean - centerMean) / 255));
  let gradient = 0, gradientCount = 0, highlights = 0, dark = 0, brightness = 0;
  for (let y = 0; y < height; y += 2) for (let x = 0; x < width; x += 2) {
    const value = luma[y * width + x]; brightness += value;
    if (value >= 250) highlights += 1;
    if (value < 42) dark += 1;
    if (x + 2 < width) { gradient += Math.abs(value - luma[y * width + x + 2]); gradientCount += 1; }
  }
  const samples = Math.ceil(height / 2) * Math.ceil(width / 2);
  const averageBrightness = brightness / samples / 255;
  const sharpness = gradientCount ? gradient / gradientCount / 255 : 0;
  const highlightRatio = highlights / samples;
  return {
    luma: new Uint8Array(luma),
    signals: {
      motionScore,
      focusReady: sharpness >= 0.055,
      exposureReady: averageBrightness >= 0.18 && averageBrightness <= 0.88 && highlightRatio <= 0.12,
      boundaryConfidence,
      spineConfidence,
      occlusionRatio: dark / samples,
    },
  };
}

export function lumaFromImageData(imageData) {
  const luma = new Uint8Array(imageData.width * imageData.height);
  for (let source = 0, target = 0; source < imageData.data.length; source += 4, target += 1) {
    luma[target] = Math.round(.2126 * imageData.data[source] + .7152 * imageData.data[source + 1] + .0722 * imageData.data[source + 2]);
  }
  return luma;
}
