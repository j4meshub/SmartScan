const labels = {
  "zh-CN": {
    missing_page: "缺少可见页码",
    duplicate_page: "疑似重复页",
    number_conflict: "相同页码内容冲突",
    number_order_conflict: "页码顺序冲突",
    number_gap_uncertain: "页码跨度过大，需确认",
    number_ambiguous: "页码识别不确定",
    expected_number_mismatch: "补扫页码与预期不一致",
    quality_review: "页面质量待复核",
    missing_side: "双页仅可靠识别到一侧",
  },
  en: {
    missing_page: "Visible page number missing",
    duplicate_page: "Possible duplicate page",
    number_conflict: "Same number, different content",
    number_order_conflict: "Page-number order conflict",
    number_gap_uncertain: "Large page-number gap needs review",
    number_ambiguous: "Page number is uncertain",
    expected_number_mismatch: "Supplement number does not match",
    quality_review: "Page quality needs review",
    missing_side: "Only one side was detected reliably",
  },
};

export function integrityIssueLabel(issue, locale = "zh-CN") {
  const base = labels[locale]?.[issue?.kind] || issue?.kind || "";
  return issue?.printed_page_label ? `${base} · ${issue.printed_page_label}` : base;
}

export function integrityDecisionOptions(issue) {
  if (!issue || issue.decision) return ["reopen"];
  if (issue.kind === "missing_page") return ["confirmed_absent", "ignored"];
  if (["duplicate_page", "number_conflict"].includes(issue.kind)) {
    return ["exclude_duplicate", "keep_both", "ignored"];
  }
  return ["ignored"];
}

export function supplementDefaults(issue, pages) {
  if (!issue || issue.kind !== "missing_page") return null;
  const right = pages.find(page => page.id === issue.related_page_id);
  return {
    expectedPageLabel: issue.printed_page_label || "",
    insertAt: right?.page_number || pages.length + 1,
  };
}

export function pageNumberBadge(page, locale = "zh-CN") {
  if (page?.book_page_number_label) {
    return locale === "zh-CN"
      ? `印刷页 ${page.book_page_number_label}`
      : `Printed ${page.book_page_number_label}`;
  }
  return locale === "zh-CN" ? "无可信印刷页码" : "No trusted printed number";
}
