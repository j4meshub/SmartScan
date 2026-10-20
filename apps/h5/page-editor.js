export const defaultCorners = () => [
  {x: 0, y: 0},
  {x: 1, y: 0},
  {x: 1, y: 1},
  {x: 0, y: 1},
];

export function clampCorner(value) {
  return Math.max(0, Math.min(1, Number(value)));
}

export function updateCorner(corners, index, x, y) {
  return corners.map((corner, cornerIndex) => cornerIndex === index
    ? {x: clampCorner(x), y: clampCorner(y)}
    : {...corner});
}

export function movePage(pages, index, delta) {
  const target = index + delta;
  if (index < 0 || index >= pages.length || target < 0 || target >= pages.length) {
    return {pages: [...pages], index};
  }
  const next = [...pages];
  [next[index], next[target]] = [next[target], next[index]];
  return {pages: next, index: target};
}

export function filterPreview(filterName) {
  if (filterName === "enhance") return "contrast(1.12) saturate(1.04)";
  if (filterName === "grayscale") return "grayscale(1) contrast(1.05)";
  if (filterName === "bw") return "grayscale(1) contrast(2.2)";
  return "none";
}

export function qualityPrompt(page, locale = "zh-CN") {
  if (!page?.quality_warning && page?.review_status !== "pending") return "";
  const warning = page.quality_warning || "needs_review";
  const chinese = {
    low_resolution: "页面分辨率偏低，建议检查文字后再确认。",
    low_contrast: "页面对比度偏低，可尝试增强滤镜并检查结果。",
    needs_review: "该页面需要人工复核。",
  };
  const english = {
    low_resolution: "Page resolution is low. Check the text before confirming.",
    low_contrast: "Page contrast is low. Try Enhance and check the result.",
    needs_review: "This page needs review.",
  };
  return (locale === "zh-CN" ? chinese : english)[warning]
    || (locale === "zh-CN" ? `页面需复核：${warning}` : `Review required: ${warning}`);
}
