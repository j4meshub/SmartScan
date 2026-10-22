const RUNNING_STATUSES = new Set(["queued", "processing"]);
const candidatePreview = value => String(value || "").trim().slice(0, 512);

export function createAiIdempotencyKey(pageId, sourceVersion, cryptoApi = globalThis.crypto) {
  if (!Number.isInteger(sourceVersion) || sourceVersion < 1) throw new Error("ai_source_version_invalid");
  if (typeof cryptoApi?.randomUUID !== "function") throw new Error("secure_random_unavailable");
  const safePage = String(pageId || "page").replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 24);
  return `h5-ai.${safePage}.v${sourceVersion}.${cryptoApi.randomUUID()}`.slice(0, 100);
}

export function latestEnhancement(enhancements, sourceVersion, enhancementKind = null) {
  const items = Array.isArray(enhancements) ? enhancements : [];
  const matchingKind = enhancementKind ? items.filter(item => item.enhancement_kind === enhancementKind) : items;
  return matchingKind.find(item => item.source_result_version === sourceVersion) || matchingKind[0] || null;
}

export function shouldPollEnhancements(enhancements) {
  return (Array.isArray(enhancements) ? enhancements : []).some(item => RUNNING_STATUSES.has(item.status));
}

export function aiCandidateSummary(enhancement) {
  const tasks = enhancement?.candidate_result?.tasks;
  if (!tasks || typeof tasks !== "object" || Array.isArray(tasks)) return [];
  const rows = [];
  const classification = tasks.classify_page;
  if (classification?.label) rows.push({kind:"classification", value:String(classification.label), confidence:classification.confidence});
  const orientation = tasks.detect_orientation;
  if ([0, 90, 180, 270].includes(orientation?.rotation_degrees)) rows.push({kind:"orientation", value:Number(orientation.rotation_degrees), confidence:orientation.confidence});
  const title = Array.isArray(tasks.extract_title?.candidates)
    ? [...tasks.extract_title.candidates].filter(item => typeof item?.text === "string" && item.text.trim()).sort((a,b) => Number(b.confidence || 0) - Number(a.confidence || 0))[0]
    : null;
  if (title) rows.push({kind:"title", value:title.text.trim(), confidence:title.confidence});
  const pageNumber = tasks.extract_page_number;
  if (pageNumber?.status === "detected" && (pageNumber.raw_label || Number.isInteger(pageNumber.normalized_number))) {
    rows.push({kind:"pageNumber", value:String(pageNumber.raw_label || pageNumber.normalized_number), confidence:pageNumber.confidence});
  }
  const complexOcr = tasks.ocr_formula;
  const blocks = Array.isArray(complexOcr?.blocks) ? complexOcr.blocks.slice(0, 40) : [];
  for (const block of blocks) {
    if (block?.block_type === "formula" && typeof block.latex_candidate === "string" && block.latex_candidate.trim()) {
      rows.push({kind:"formula", value:candidatePreview(block.latex_candidate), confidence:block.confidence});
      continue;
    }
    if (block?.block_type === "table" && Array.isArray(block.cells)) {
      const cells = block.cells.slice(0, 200)
        .filter(cell => Number.isInteger(cell?.row) && Number.isInteger(cell?.column) && typeof cell?.text_candidate === "string")
        .sort((left,right) => left.row-right.row || left.column-right.column);
      const rowValues = new Map();
      for (const cell of cells) {
        const value=cell.text_candidate.trim();
        if (!value) continue;
        if (!rowValues.has(cell.row)) rowValues.set(cell.row, []);
        rowValues.get(cell.row).push(value);
      }
      const value=candidatePreview([...rowValues.values()].map(row => row.join(" | ")).join(" / "));
      if (value) rows.push({kind:"table", value, confidence:block.confidence});
      continue;
    }
    if (block?.block_type === "layout" && typeof block.text_candidate === "string" && block.text_candidate.trim()) {
      rows.push({kind:"layout", value:candidatePreview(block.text_candidate), confidence:block.confidence});
    }
  }
  return rows;
}

export function confidencePercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.round(Math.max(0, Math.min(1, number)) * 100);
}

export function canDecideEnhancement(enhancement, activeVersion) {
  return enhancement?.status === "candidate_ready" && enhancement.source_result_version === activeVersion;
}

export function sourceVersionPreview(enhancement, page) {
  if (!enhancement || enhancement.status !== "accepted") return null;
  if (!Number.isInteger(enhancement.source_result_version) || enhancement.source_result_version < 1) return null;
  if (!page || page.active_result_version === enhancement.source_result_version) return null;
  return enhancement.source_result_version;
}
