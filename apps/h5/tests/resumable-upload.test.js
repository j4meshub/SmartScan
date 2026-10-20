import assert from "node:assert/strict";
import test from "node:test";

import {fileMimeType, uploadResumable, uploadResumeKey} from "../resumable-upload.js";

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}

function fakeFile(contents = "abcdefghij", name = "page.jpg", type = "image/jpeg") {
  const blob = new Blob([contents], {type});
  Object.defineProperties(blob, {
    name: {value: name},
    lastModified: {value: 123456},
  });
  return blob;
}

const hashBlob = async blob => `hash-${blob.size}`;

test("断网重试沿用项目与幂等键且不重传已确认分片", async () => {
  const storage = new MemoryStorage();
  const file = fakeFile();
  const storageKey = uploadResumeKey(file, "弱网测试", "document");
  const chunkAttempts = new Map();
  const uploadBodies = [];
  const progress = [];
  let projectCreates = 0;
  let uploadCreates = 0;

  const request = async (path, options) => {
    if (path === "/v1/projects") {
      projectCreates += 1;
      return {id: "project-1"};
    }
    if (path === "/v1/uploads") {
      uploadCreates += 1;
      uploadBodies.push(JSON.parse(options.body));
      return {
        id: "upload-1",
        status: "pending",
        chunk_size: 4,
        total_chunks: 3,
        received_chunks: uploadCreates === 1 ? [] : [0],
      };
    }
    const chunkMatch = path.match(/\/chunks\/(\d+)$/);
    if (chunkMatch) {
      const index = Number(chunkMatch[1]);
      chunkAttempts.set(index, (chunkAttempts.get(index) || 0) + 1);
      if (index === 1 && chunkAttempts.get(index) === 1) throw new TypeError("network offline");
      return {chunk_index: index};
    }
    if (path === "/v1/uploads/upload-1/complete") return {id: "page-1"};
    throw new Error(`unexpected request: ${path}`);
  };

  const options = {
    file,
    title: "弱网测试",
    mode: "document",
    request,
    storage,
    randomUUID: () => "same-idempotency-key",
    hashBlob,
    onProgress: (uploaded, total) => progress.push([uploaded, total]),
  };

  await assert.rejects(uploadResumable(options), /network offline/);
  assert.notEqual(storage.getItem(storageKey), null);
  assert.deepEqual([...chunkAttempts], [[0, 1], [1, 1]]);

  assert.deepEqual(await uploadResumable(options), {id: "page-1"});
  assert.equal(storage.getItem(storageKey), null);
  assert.equal(projectCreates, 1);
  assert.equal(uploadCreates, 2);
  assert.equal(uploadBodies[0].idempotency_key, uploadBodies[1].idempotency_key);
  assert.equal(chunkAttempts.get(0), 1, "已确认的第 0 片不得重传");
  assert.equal(chunkAttempts.get(1), 2);
  assert.equal(chunkAttempts.get(2), 1);
  assert.deepEqual(progress, [[0, 10], [4, 10], [4, 10], [8, 10], [10, 10]]);
});

test("过期会话更换幂等键但保留原项目", async () => {
  const storage = new MemoryStorage();
  const file = fakeFile("abcd");
  const keys = ["first-key", "second-key"];
  const uploadBodies = [];
  let projectCreates = 0;

  const request = async (path, options) => {
    if (path === "/v1/projects") {
      projectCreates += 1;
      return {id: "project-1"};
    }
    if (path === "/v1/uploads") {
      uploadBodies.push(JSON.parse(options.body));
      if (uploadBodies.length === 1) return {status: "expired"};
      return {id: "upload-2", status: "pending", chunk_size: 4, total_chunks: 1, received_chunks: []};
    }
    if (path.endsWith("/chunks/0")) return {chunk_index: 0};
    if (path.endsWith("/complete")) return {id: "page-2"};
    throw new Error(`unexpected request: ${path}`);
  };

  await uploadResumable({
    file,
    title: "过期恢复",
    mode: "document",
    request,
    storage,
    randomUUID: () => keys.shift(),
    hashBlob,
  });

  assert.equal(projectCreates, 1);
  assert.equal(uploadBodies[0].project_id, "project-1");
  assert.equal(uploadBodies[1].project_id, "project-1");
  assert.notEqual(uploadBodies[0].idempotency_key, uploadBodies[1].idempotency_key);
});

test("未知 MIME 可按扩展名安全回退", () => {
  assert.equal(fileMimeType(fakeFile("x", "page.JPEG", "")), "image/jpeg");
  assert.equal(fileMimeType(fakeFile("x", "page.heic", "application/octet-stream")), "image/heic");
});
