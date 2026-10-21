import assert from "node:assert/strict";
import test from "node:test";

import {canDismissExamSuggestion, defaultCorners, examSuggestionPrompt, filterPreview, movePage, qualityPrompt, updateCorner} from "../page-editor.js";

test("四角坐标被限制在归一化画布范围", () => {
  const corners = updateCorner(defaultCorners(), 0, -0.2, 1.4);
  assert.deepEqual(corners[0], {x: 0, y: 1});
  assert.deepEqual(corners[1], {x: 1, y: 0});
});

test("试卷建议仅对当前可见结果显示并提供双语说明", () => {
  const page = {exam_suggestion_visible: true, exam_result_version: 3, exam_confidence_band: "high"};
  assert.match(examSuggestionPrompt(page, "zh-CN"), /试卷净化/);
  assert.match(examSuggestionPrompt({...page, exam_confidence_band: "medium"}, "en"), /Switch/i);
  assert.equal(examSuggestionPrompt({...page, exam_suggestion_visible: false}), "");
  assert.equal(canDismissExamSuggestion(page), true);
  assert.equal(canDismissExamSuggestion({...page, exam_result_version: null}), false);
});

test("页面移动不会越界且返回新的顺序", () => {
  const pages = [{id: "a"}, {id: "b"}, {id: "c"}];
  assert.deepEqual(movePage(pages, 1, -1), {pages: [{id: "b"}, {id: "a"}, {id: "c"}], index: 0});
  assert.deepEqual(movePage(pages, 0, -1), {pages, index: 0});
  assert.deepEqual(pages.map(page => page.id), ["a", "b", "c"]);
});

test("滤镜预览和质量提示提供稳定双语文案", () => {
  assert.match(filterPreview("enhance"), /contrast/);
  assert.match(filterPreview("grayscale"), /grayscale/);
  assert.equal(filterPreview("original"), "none");
  assert.match(qualityPrompt({quality_warning: "low_contrast"}, "zh-CN"), /对比度/);
  assert.match(qualityPrompt({review_status: "pending"}, "en"), /review/i);
  assert.equal(qualityPrompt({review_status: "not_required"}), "");
});
