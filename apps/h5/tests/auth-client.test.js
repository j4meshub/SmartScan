import assert from "node:assert/strict";
import test from "node:test";

import {AuthClient, authStorageKeys, deviceHeaders, getOrCreateDeviceId} from "../auth-client.js";

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

const cryptoApi = {randomUUID: () => "11111111-2222-4333-8444-555555555555"};

function jsonResponse(status, body) {
  return {status, ok: status >= 200 && status < 300, json: async () => body};
}

function client(fetchImpl, onAuthLost = () => {}) {
  return new AuthClient({
    api: "https://api.example.test/",
    fetchImpl,
    sessionStorage: new MemoryStorage(),
    deviceStorage: new MemoryStorage(),
    cryptoApi,
    deviceName: "测试 H5",
    onAuthLost,
  });
}

test("设备标识稳定且设备名按 UTF-8 编码", () => {
  const storage = new MemoryStorage();
  const first = getOrCreateDeviceId(storage, cryptoApi);
  const second = getOrCreateDeviceId(storage, {randomUUID: () => "different"});
  assert.equal(first, "web:11111111-2222-4333-8444-555555555555");
  assert.equal(second, first);
  assert.deepEqual(deviceHeaders(first, "企业微信 H5"), {
    "X-Device-ID": first,
    "X-Device-Name": "%E4%BC%81%E4%B8%9A%E5%BE%AE%E4%BF%A1%20H5",
    "X-Device-Platform": "web",
  });
});

test("登录会把访问与刷新令牌原子写入会话存储", async () => {
  const calls = [];
  const auth = client(async (url, options) => {
    calls.push({url, options});
    return jsonResponse(200, {
      access_token: "access-1",
      refresh_token: "refresh-1",
      expires_at: "2026-10-20T12:00:00Z",
      session_id: "session-1",
    });
  });
  await auth.login("demo", "correct-password");
  assert.equal(auth.session.access_token, "access-1");
  assert.equal(auth.session.refresh_token, "refresh-1");
  assert.equal(calls[0].options.credentials, "include");
  assert.equal(calls[0].options.headers["X-Device-Platform"], "web");
  assert.equal(calls[0].options.headers.Authorization, undefined);
});

test("401 会单次轮换刷新令牌并重放原请求", async () => {
  const calls = [];
  const auth = client(async (url, options) => {
    calls.push({url, options});
    if (url.endsWith("/v1/auth/refresh")) {
      return jsonResponse(200, {access_token: "access-2", refresh_token: "refresh-2"});
    }
    if (options.headers.Authorization === "Bearer access-1") {
      return jsonResponse(401, {detail: "session expired"});
    }
    return jsonResponse(200, [{id: "project-1"}]);
  });
  auth.setSession({access_token: "access-1", refresh_token: "refresh-1"});
  const result = await auth.request("/v1/projects");
  assert.deepEqual(result, [{id: "project-1"}]);
  assert.equal(auth.session.access_token, "access-2");
  assert.equal(auth.session.refresh_token, "refresh-2");
  assert.equal(calls.length, 3);
  assert.equal(JSON.parse(calls[1].options.body).refresh_token, "refresh-1");
});

test("并发 401 共享同一次刷新请求", async () => {
  let refreshCalls = 0;
  const auth = client(async (url, options) => {
    if (url.endsWith("/v1/auth/refresh")) {
      refreshCalls += 1;
      await Promise.resolve();
      return jsonResponse(200, {access_token: "access-2", refresh_token: "refresh-2"});
    }
    return options.headers.Authorization === "Bearer access-1"
      ? jsonResponse(401, {detail: "session expired"})
      : jsonResponse(200, {ok: true});
  });
  auth.setSession({access_token: "access-1", refresh_token: "refresh-1"});
  await Promise.all([auth.request("/v1/me"), auth.request("/v1/projects")]);
  assert.equal(refreshCalls, 1);
});

test("刷新失败会清除会话并通知界面", async () => {
  let lost = 0;
  const auth = client(async url => {
    if (url.endsWith("/v1/auth/refresh")) return jsonResponse(401, {detail: "refresh_token_replayed"});
    return jsonResponse(401, {detail: "session expired"});
  }, () => { lost += 1; });
  auth.setSession({access_token: "access-1", refresh_token: "refresh-1"});
  await assert.rejects(() => auth.request("/v1/me"), /refresh_token_replayed/);
  assert.equal(auth.session, null);
  assert.equal(lost, 1);
});

test("刷新响应缺少新刷新令牌时拒绝复用旧令牌", async () => {
  let lost = 0;
  const auth = client(async url => url.endsWith("/v1/auth/refresh")
    ? jsonResponse(200, {access_token: "access-2"})
    : jsonResponse(401, {detail: "session expired"}), () => { lost += 1; });
  auth.setSession({access_token: "access-1", refresh_token: "refresh-1"});
  await assert.rejects(() => auth.request("/v1/me"), /refresh_response_invalid/);
  assert.equal(auth.session, null);
  assert.equal(lost, 1);
});

test("企业微信回调与短信绑定复用既有认证契约", async () => {
  const calls = [];
  const auth = client(async (url, options) => {
    calls.push({url, options});
    if (url.includes("/callback?")) {
      return jsonResponse(200, {action: "require_phone_binding", binding_ticket: "ticket-1"});
    }
    if (url.endsWith("/sms/challenges")) {
      return jsonResponse(201, {challenge_id: "challenge-1", retry_after_seconds: 60});
    }
    return jsonResponse(200, {access_token: "access-wecom", refresh_token: "refresh-wecom"});
  });
  const callback = await auth.completeWeComCallback("code-value", "state-value");
  assert.equal(callback.binding_ticket, "ticket-1");
  await auth.requestBindingCode("+8613800000000");
  await auth.bindWeComPhone({
    bindingTicket: callback.binding_ticket,
    phone: "+8613800000000",
    challengeId: "challenge-1",
    code: "246810",
  });
  assert.equal(auth.session.refresh_token, "refresh-wecom");
  assert.match(calls[0].url, /code=code-value&state=state-value/);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    phone: "+8613800000000",
    purpose: "wecom_binding",
  });
  assert.equal(JSON.parse(calls[2].options.body).binding_ticket, "ticket-1");
});

test("注销无论服务端结果如何都清理浏览器会话", async () => {
  const auth = client(async () => jsonResponse(503, {detail: "temporary_error"}));
  auth.setSession({access_token: "access-1", refresh_token: "refresh-1"});
  await assert.rejects(() => auth.logout(), /temporary_error/);
  assert.equal(auth.session, null);
  assert.equal(auth.sessionStorage.getItem(authStorageKeys.session), null);
});
