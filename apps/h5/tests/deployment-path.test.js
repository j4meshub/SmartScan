import assert from "node:assert/strict";
import test from "node:test";

import {defaultApiBase} from "../deployment-path.js";

test("本机试用继续直连开发 API", () => {
  assert.equal(
    defaultApiBase({hostname: "localhost"}, "http://localhost:8080/smartscan/"),
    "http://localhost:8000",
  );
  assert.equal(
    defaultApiBase({hostname: "127.0.0.1"}, "http://127.0.0.1:8080/"),
    "http://localhost:8000",
  );
});

test("共享入口按文档基路径生成 API 地址", () => {
  assert.equal(
    defaultApiBase({hostname: "shared-host.internal"}, "http://shared-host.internal:8077/smartscan/"),
    "http://shared-host.internal:8077/smartscan/api",
  );
});

test("根路径部署保持原有 API 地址", () => {
  assert.equal(
    defaultApiBase({hostname: "scan.example.test"}, "https://scan.example.test/"),
    "https://scan.example.test/api",
  );
});
