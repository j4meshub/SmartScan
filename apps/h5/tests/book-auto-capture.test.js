import assert from "node:assert/strict";
import test from "node:test";

import {analyzeBookLuma, initialBookAutoCaptureState, reduceBookAutoCapture} from "../book-auto-capture.js";

const ready = {motionScore: 0, focusReady: true, exposureReady: true, boundaryConfidence: .9, spineConfidence: .1, occlusionRatio: .02};

test("自动快门必须先检测翻页再连续稳定三帧", () => {
  let state = initialBookAutoCaptureState();
  for (let i = 0; i < 5; i += 1) state = reduceBookAutoCapture(state, {type: "frame", signals: ready});
  assert.equal(state.phase, "WAIT_PAGE");
  state = reduceBookAutoCapture(state, {type: "frame", signals: {...ready, motionScore: .2}});
  for (let i = 0; i < 3; i += 1) state = reduceBookAutoCapture(state, {type: "frame", signals: ready});
  assert.equal(state.phase, "CAPTURE");
});

test("边界、书脊和遮挡不满足时给出稳定阻塞原因", () => {
  for (const [change, blocker] of [
    [{boundaryConfidence: .2}, "boundary_incomplete"],
    [{spineConfidence: 0}, "spine_not_found"],
    [{occlusionRatio: .5}, "occlusion_detected"],
  ]) {
    let state = reduceBookAutoCapture(initialBookAutoCaptureState(), {type: "frame", signals: {...ready, motionScore: .2}});
    for (let i = 0; i < 3; i += 1) state = reduceBookAutoCapture(state, {type: "frame", signals: {...ready, ...change}});
    assert.equal(state.blocker, blocker);
  }
});

test("浏览器亮度分析检测翻页运动和非中心暗书脊", () => {
  const width = 100, height = 80;
  const first = new Uint8Array(width * height).fill(220);
  const changed = new Uint8Array(first);
  for (let y = 0; y < height; y += 1) for (let x = 45; x < 51; x += 1) changed[y * width + x] = 30;
  const result = analyzeBookLuma(changed, width, height, first);
  assert.ok(result.signals.motionScore > 0);
  assert.ok(result.signals.spineConfidence > .035);
  assert.ok(result.signals.occlusionRatio < .2);
});
