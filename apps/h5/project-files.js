const ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "baseline_processing",
  "baseline_ready",
  "optional_enhancing",
  "failed_retryable",
]);

export function projectJobs(jobs, projectId) {
  return jobs
    .filter(job => job.project_id === projectId)
    .sort((first, second) => Date.parse(second.updated_at) - Date.parse(first.updated_at));
}

export function shouldPollJobs(jobs) {
  return jobs.some(job => ACTIVE_JOB_STATUSES.has(job.status));
}

export function jobStatusLabel(status, locale = "zh-CN") {
  const labels = {
    queued: ["等待处理", "Queued"],
    baseline_processing: ["基础处理中", "Processing"],
    baseline_ready: ["基础结果已就绪", "Baseline ready"],
    optional_enhancing: ["增强处理中", "Enhancing"],
    ready: ["处理完成", "Ready"],
    failed_retryable: ["等待重试", "Retry pending"],
    failed_final: ["处理失败", "Failed"],
    cancel_requested: ["正在取消", "Canceling"],
    canceled: ["已取消", "Canceled"],
  };
  const pair = labels[status] || [status, status];
  return pair[locale === "zh-CN" ? 0 : 1];
}

export function jobKindLabel(kind, locale = "zh-CN") {
  const labels = {
    baseline: ["基础处理", "Baseline processing"],
    ocr: ["文字识别", "Text recognition"],
    enhancement: ["可选增强", "Optional enhancement"],
  };
  const pair = labels[kind] || [kind, kind];
  return pair[locale === "zh-CN" ? 0 : 1];
}

export function exportQualityLabel(quality, locale = "zh-CN") {
  const labels = {clear:["清晰","Clear"],balanced:["均衡","Balanced"],small:["小文件","Small file"]};
  const pair = labels[quality] || [quality, quality];
  return pair[locale === "zh-CN" ? 0 : 1];
}

export function exportStatusLabel(status, locale = "zh-CN") {
  const labels = {ready:["已就绪","Ready"],failed:["失败","Failed"],generating:["生成中","Generating"]};
  const pair = labels[status] || [status, status];
  return pair[locale === "zh-CN" ? 0 : 1];
}

export function downloadBlob({blob, fileName, documentApi = globalThis.document, urlApi = globalThis.URL, schedule = globalThis.setTimeout}) {
  const url = urlApi.createObjectURL(blob);
  const anchor = documentApi.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.rel = "noopener";
  anchor.click();
  schedule(() => urlApi.revokeObjectURL(url), 1000);
  return "downloaded";
}

export async function shareOrDownload({
  blob,
  fileName,
  mimeType,
  title,
  navigatorApi = globalThis.navigator,
  documentApi = globalThis.document,
  urlApi = globalThis.URL,
  FileCtor = globalThis.File,
  schedule = globalThis.setTimeout,
}) {
  const canBuildFile = typeof FileCtor === "function";
  const file = canBuildFile ? new FileCtor([blob], fileName, {type: mimeType || blob.type}) : null;
  const shareData = {title, files: file ? [file] : []};
  if (file && typeof navigatorApi.share === "function" && navigatorApi.canShare?.(shareData)) {
    try {
      await navigatorApi.share(shareData);
      return "shared";
    } catch (error) {
      if (error?.name === "AbortError") return "canceled";
    }
  }
  return downloadBlob({blob, fileName, documentApi, urlApi, schedule});
}
