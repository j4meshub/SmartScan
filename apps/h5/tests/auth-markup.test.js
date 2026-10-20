import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const htmlPath = new URL("../index.html", import.meta.url);

test("登录页包含本地登录、企业微信、手机号绑定和退出入口", async () => {
  const html = await readFile(htmlPath, "utf8");
  for (const id of [
    "loginForm",
    "wecomLoginButton",
    "phoneBindingForm",
    "bindingPhone",
    "sendBindingCode",
    "logoutButton",
  ]) {
    assert.equal((html.match(new RegExp(`id=["']${id}["']`, "g")) || []).length, 1, id);
  }
  assert.match(html, /autocomplete="one-time-code"/);
  assert.match(html, /data-i18n="bindingTitle"/);
});
