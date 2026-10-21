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
  assert.match(html, /id="bookAutoEnabled"[^>]*type="checkbox"/);
  assert.match(html, /id="bookAutoStatus"[^>]*aria-live="polite"/);
});

test("项目页包含四角、旋转、滤镜、排序和质量复核入口", async () => {
  const html = await readFile(htmlPath, "utf8");
  for (const id of [
    "editorDialog",
    "cornerOverlay",
    "rotatePageLeft",
    "rotatePageRight",
    "movePageLeft",
    "movePageRight",
    "savePageEdit",
    "confirmReview",
    "examSuggestion",
    "dismissExamSuggestion",
  ]) assert.match(html, new RegExp(`id=["']${id}["']`));
  assert.equal((html.match(/data-page-filter=/g) || []).length, 4);
  assert.equal((html.match(/data-corner=/g) || []).length, 4);
});

test("项目恢复界面包含任务状态、导出、下载与分享入口", async () => {
  const html = await readFile(htmlPath, "utf8");
  for (const id of [
    "projectJobList",
    "refreshProjectFiles",
    "exportFormat",
    "exportQuality",
    "exportOcr",
    "createExport",
    "exportList",
  ]) assert.match(html, new RegExp(`id=["']${id}["']`));
});
