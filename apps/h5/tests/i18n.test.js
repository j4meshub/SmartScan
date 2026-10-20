import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

import {copy, editorCopy, missingLocaleKeys} from "../i18n.js";

const htmlPath = new URL("../index.html", import.meta.url);

function attributeValues(html, attribute) {
  return [...html.matchAll(new RegExp(`${attribute}=["']([^"']+)["']`, "g"))].map(match => match[1]);
}

test("中英文主界面与编辑器词条键完全一致", () => {
  assert.deepEqual(missingLocaleKeys(copy), []);
  assert.deepEqual(missingLocaleKeys(editorCopy), []);
  for (const dictionary of [copy, editorCopy]) {
    for (const locale of ["zh-CN", "en"]) {
      assert.equal(Object.values(dictionary[locale]).some(value => !value.trim()), false);
    }
  }
});

test("HTML 的文本、替代文本与无障碍名称都有双语词条", async () => {
  const html = await readFile(htmlPath, "utf8");
  for (const key of attributeValues(html, "data-i18n")) assert.ok(copy["zh-CN"][key] && copy.en[key], key);
  for (const key of attributeValues(html, "data-editor-i18n")) assert.ok(editorCopy["zh-CN"][key] && editorCopy.en[key], key);
  for (const attribute of ["data-i18n-aria-label", "data-i18n-alt"]) {
    for (const key of attributeValues(html, attribute)) assert.ok(copy["zh-CN"][key] && copy.en[key], key);
  }
  assert.doesNotMatch(html, /aria-label="(?:Close|Pages|Main navigation|Scan modes)"/);
});

test("四角裁切控制可由键盘聚焦并暴露滑块语义", async () => {
  const html = await readFile(htmlPath, "utf8");
  assert.equal((html.match(/data-corner=/g) || []).length, 4);
  assert.equal((html.match(/role="slider"/g) || []).length, 4);
  assert.equal((html.match(/tabindex="0"/g) || []).length, 4);
});
