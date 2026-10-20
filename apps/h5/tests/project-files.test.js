import test from "node:test";
import assert from "node:assert/strict";

import {exportQualityLabel, exportStatusLabel, jobKindLabel, jobStatusLabel, projectJobs, shareOrDownload, shouldPollJobs} from "../project-files.js";

test("任务按项目过滤并按更新时间倒序恢复", () => {
  const jobs = [
    {id: "old", project_id: "p1", status: "ready", updated_at: "2026-01-01T00:00:00Z"},
    {id: "other", project_id: "p2", status: "queued", updated_at: "2026-03-01T00:00:00Z"},
    {id: "new", project_id: "p1", status: "baseline_processing", updated_at: "2026-02-01T00:00:00Z"},
  ];
  assert.deepEqual(projectJobs(jobs, "p1").map(job => job.id), ["new", "old"]);
  assert.equal(shouldPollJobs(projectJobs(jobs, "p1")), true);
  assert.equal(shouldPollJobs([{status: "ready"}, {status: "failed_final"}]), false);
  assert.equal(jobStatusLabel("ready", "zh-CN"), "处理完成");
  assert.equal(jobStatusLabel("failed_final", "en"), "Failed");
  assert.equal(jobKindLabel("baseline", "zh-CN"), "基础处理");
  assert.equal(exportQualityLabel("balanced", "en"), "Balanced");
  assert.equal(exportStatusLabel("ready", "zh-CN"), "已就绪");
});

test("支持文件分享时调用 Web Share", async () => {
  const shared = [];
  class FakeFile {
    constructor(parts, name, options) { this.parts = parts; this.name = name; this.type = options.type; }
  }
  const result = await shareOrDownload({
    blob: {type: "application/pdf"},
    fileName: "scan.pdf",
    mimeType: "application/pdf",
    title: "扫描件",
    navigatorApi: {canShare: data => data.files[0].name === "scan.pdf", share: data => shared.push(data)},
    FileCtor: FakeFile,
  });
  assert.equal(result, "shared");
  assert.equal(shared[0].files[0].name, "scan.pdf");
});

test("Web Share 不可用时回退为本地下载", async () => {
  const anchors = [];
  const revoked = [];
  class FakeFile {}
  const documentApi = {createElement: () => { const anchor = {click(){ this.clicked = true; }}; anchors.push(anchor); return anchor; }};
  const urlApi = {createObjectURL: () => "blob:export", revokeObjectURL: url => revoked.push(url)};
  const result = await shareOrDownload({
    blob: {type: "image/jpeg"},
    fileName: "page.jpg",
    mimeType: "image/jpeg",
    title: "扫描件",
    navigatorApi: {},
    documentApi,
    urlApi,
    FileCtor: FakeFile,
    schedule: callback => callback(),
  });
  assert.equal(result, "downloaded");
  assert.equal(anchors[0].download, "page.jpg");
  assert.equal(anchors[0].clicked, true);
  assert.deepEqual(revoked, ["blob:export"]);
});
