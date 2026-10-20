import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const htmlPath = new URL("../index.html", import.meta.url);

test("拍摄入口同时提供实时相机、系统相机文件兜底和预览", async () => {
  const html = await readFile(htmlPath, "utf8");
  assert.match(html, /id="openCamera"/);
  assert.match(html, /id="cameraPreview"[^>]*playsinline/);
  assert.match(html, /id="pageFile"[^>]*capture="environment"/);
  assert.match(html, /id="pageFile"[^>]*accept="image\/jpeg,image\/png,image\/webp,image\/heic"/);
  assert.match(html, /id="capturePreview"/);
});
