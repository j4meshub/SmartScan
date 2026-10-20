const supportedMimeTypes = new Set(["image/jpeg", "image/png", "image/webp", "image/heic"]);

export function fileMimeType(file) {
  if (supportedMimeTypes.has(file.type)) return file.type;
  const extension = file.name.split(".").pop()?.toLowerCase();
  return ({jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", heic: "image/heic"})[extension] || file.type;
}

export function uploadResumeKey(file, title, mode) {
  return `smartscan.upload.${file.name}:${file.size}:${file.lastModified}:${mode}:${title}`;
}

export async function sha256Blob(blob, cryptoImpl = globalThis.crypto) {
  const buffer = await blob.arrayBuffer();
  const digest = await cryptoImpl.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

function readResume(storage, storageKey) {
  try {
    return JSON.parse(storage.getItem(storageKey) || "null");
  } catch {
    storage.removeItem(storageKey);
    return null;
  }
}

function confirmedChunkBytes(received, chunkSize, fileSize) {
  return [...received].reduce(
    (sum, index) => sum + Math.min(chunkSize, fileSize - index * chunkSize),
    0,
  );
}

export async function uploadResumable({
  file,
  title,
  mode,
  request,
  storage,
  randomUUID = () => globalThis.crypto.randomUUID(),
  hashBlob = sha256Blob,
  onProgress = () => {},
}) {
  const storageKey = uploadResumeKey(file, title, mode);
  let resume = readResume(storage, storageKey);
  if (!resume) {
    const project = await request("/v1/projects", {
      method: "POST",
      body: JSON.stringify({title, mode, reading_order: "ltr"}),
    });
    resume = {projectId: project.id, idempotencyKey: randomUUID().replaceAll("-", "")};
    storage.setItem(storageKey, JSON.stringify(resume));
  }

  const fileHash = await hashBlob(file);
  const createUploadWithHash = async () => {
    const options = {
      method: "POST",
      body: JSON.stringify({
        project_id: resume.projectId,
        file_name: file.name,
        mime_type: fileMimeType(file),
        size_bytes: file.size,
        sha256: fileHash,
        idempotency_key: resume.idempotencyKey,
      }),
    };
    return request("/v1/uploads", options);
  };
  let upload = await createUploadWithHash();
  if (upload.status === "expired") {
    resume.idempotencyKey = randomUUID().replaceAll("-", "");
    storage.setItem(storageKey, JSON.stringify(resume));
    upload = await createUploadWithHash();
  }

  const received = new Set(
    upload.received_chunks.filter(
      index => Number.isInteger(index) && index >= 0 && index < upload.total_chunks,
    ),
  );
  let uploadedBytes = confirmedChunkBytes(received, upload.chunk_size, file.size);
  onProgress(uploadedBytes, file.size);

  for (let index = 0; index < upload.total_chunks; index += 1) {
    if (received.has(index)) continue;
    const start = index * upload.chunk_size;
    const chunk = file.slice(start, Math.min(start + upload.chunk_size, file.size));
    const chunkHash = await hashBlob(chunk);
    await request(`/v1/uploads/${upload.id}/chunks/${index}`, {
      method: "PUT",
      headers: {"Content-Type": "application/octet-stream", "X-Chunk-Sha256": chunkHash},
      body: chunk,
    });
    uploadedBytes += chunk.size;
    onProgress(uploadedBytes, file.size);
  }

  const page = await request(`/v1/uploads/${upload.id}/complete`, {method: "POST"});
  storage.removeItem(storageKey);
  return page;
}
