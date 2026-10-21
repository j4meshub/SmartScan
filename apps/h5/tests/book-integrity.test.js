import assert from "node:assert/strict";
import test from "node:test";

import {
  integrityDecisionOptions,
  integrityIssueLabel,
  pageNumberBadge,
  supplementDefaults,
} from "../book-integrity.js";

test("完整性问题提供稳定双语说明和类型化决策", () => {
  const missing = {kind: "missing_page", printed_page_label: "12", decision: null};
  assert.match(integrityIssueLabel(missing, "zh-CN"), /缺少.*12/);
  assert.match(integrityIssueLabel(missing, "en"), /missing.*12/i);
  assert.deepEqual(integrityDecisionOptions(missing), ["confirmed_absent", "ignored"]);
  assert.deepEqual(
    integrityDecisionOptions({kind: "duplicate_page", decision: null}),
    ["exclude_duplicate", "keep_both", "ignored"],
  );
  assert.deepEqual(integrityDecisionOptions({...missing, decision: "confirmed_absent"}), ["reopen"]);
});

test("缺页补扫位置使用右侧逻辑页且不伪造无页码标签", () => {
  const pages = [{id: "left", page_number: 3}, {id: "right", page_number: 4}];
  assert.deepEqual(
    supplementDefaults(
      {kind: "missing_page", related_page_id: "right", printed_page_label: "12"},
      pages,
    ),
    {expectedPageLabel: "12", insertAt: 4},
  );
  assert.equal(pageNumberBadge({book_page_number_label: "xii"}, "zh-CN"), "印刷页 xii");
  assert.match(pageNumberBadge({}, "en"), /No trusted/);
});
