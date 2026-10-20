import assert from "node:assert/strict";
import test from "node:test";

import {
  CameraUnavailableError,
  cameraBlobToFile,
  cameraCapabilities,
  captureCameraPhoto,
  openEnvironmentCamera,
  stopCamera,
} from "../camera.js";

test("能力检测始终保留系统拍照文件兜底", () => {
  assert.deepEqual(cameraCapabilities({}), {
    realtimeCamera: false,
    imageCapture: false,
    systemCaptureFallback: true,
  });
  assert.deepEqual(
    cameraCapabilities({mediaDevices: {getUserMedia() {}}, imageCaptureCtor: class {}}),
    {realtimeCamera: true, imageCapture: true, systemCaptureFallback: true},
  );
});

test("优先打开后置相机并可停止全部轨道", async () => {
  const stopped = [];
  const stream = {
    getTracks: () => [{stop: () => stopped.push("video")}, {stop: () => stopped.push("audio")}],
  };
  let constraints;
  const mediaDevices = {
    async getUserMedia(value) {
      constraints = value;
      return stream;
    },
  };
  const videoElement = {
    setAttribute(name, value) { this[name] = value; },
    async play() { this.played = true; },
  };

  assert.equal(await openEnvironmentCamera({mediaDevices, videoElement}), stream);
  assert.deepEqual(constraints, {audio: false, video: {facingMode: {ideal: "environment"}}});
  assert.equal(videoElement.srcObject, stream);
  assert.equal(videoElement.played, true);
  assert.equal(videoElement.playsinline, "");

  stopCamera(stream);
  assert.deepEqual(stopped, ["video", "audio"]);
});

test("实时相机不可用或授权失败时返回稳定错误供文件兜底", async () => {
  await assert.rejects(
    openEnvironmentCamera({mediaDevices: undefined, videoElement: {}}),
    error => error instanceof CameraUnavailableError && error.code === "camera_not_supported",
  );
  await assert.rejects(
    openEnvironmentCamera({
      mediaDevices: {getUserMedia: async () => { throw new Error("permission details"); }},
      videoElement: {},
    }),
    error => error instanceof CameraUnavailableError && error.code === "camera_open_failed",
  );

  let stopped = false;
  const videoElement = {
    srcObject: null,
    setAttribute() {},
    async play() { throw new Error("autoplay blocked"); },
  };
  await assert.rejects(
    openEnvironmentCamera({
      mediaDevices: {
        getUserMedia: async () => ({getTracks: () => [{stop: () => { stopped = true; }}]}),
      },
      videoElement,
    }),
    error => error instanceof CameraUnavailableError && error.code === "camera_open_failed",
  );
  assert.equal(stopped, true);
  assert.equal(videoElement.srcObject, null);
});

test("可用时使用 ImageCapture 拍照并生成上传文件", async () => {
  const track = {id: "track-1"};
  const stream = {getVideoTracks: () => [track]};
  class FakeImageCapture {
    constructor(value) { assert.equal(value, track); }
    async takePhoto() { return new Blob(["photo"], {type: "image/jpeg"}); }
  }

  const blob = await captureCameraPhoto({stream, imageCaptureCtor: FakeImageCapture});
  const file = cameraBlobToFile(blob, 123456);
  assert.equal(file.name, "camera_123456.jpg");
  assert.equal(file.type, "image/jpeg");
  assert.equal(file.size, 5);
});

test("ImageCapture 不可用时从视频帧生成 JPEG", async () => {
  let drawn = false;
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({drawImage: () => { drawn = true; }}),
    toBlob: callback => callback(new Blob(["frame"], {type: "image/jpeg"})),
  };
  const blob = await captureCameraPhoto({
    stream: {getVideoTracks: () => [{id: "track-1"}]},
    videoElement: {videoWidth: 1280, videoHeight: 720},
    imageCaptureCtor: undefined,
    canvasFactory: () => canvas,
  });
  assert.equal(drawn, true);
  assert.equal(canvas.width, 1280);
  assert.equal(canvas.height, 720);
  assert.equal(blob.type, "image/jpeg");
});
