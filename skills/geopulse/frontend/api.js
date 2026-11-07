let csrfToken = "";

export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || `请求失败（${status}）`;
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function setCsrf(value) { csrfToken = value || ""; }

async function parseResponse(response) {
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response.text();
}

export async function request(path, options = {}) {
  const method = options.method || "GET";
  const headers = new Headers(options.headers || {});
  const rawBody = options.body instanceof FormData || options.body instanceof Blob ||
    options.body instanceof ArrayBuffer || ArrayBuffer.isView(options.body) || typeof options.body === "string";
  if (options.body !== undefined && !rawBody) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, {
    ...options, method, headers, credentials: "same-origin",
    body: options.body !== undefined && !rawBody ? JSON.stringify(options.body) : options.body,
  });
  const data = await parseResponse(response);
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new CustomEvent("geopulse:unauthorized"));
    throw new ApiError(response.status, data?.detail || data);
  }
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  delete: (path) => request(path, { method: "DELETE" }),
  upload: (path, body, sha256) => request(path, { method: "POST", body, headers: {
    "Content-Type": "application/octet-stream", "X-Content-SHA256": sha256,
  } }),
};

export function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

export async function download(path, filename) {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) {
    const data = await parseResponse(response);
    throw new ApiError(response.status, data?.detail || data);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
