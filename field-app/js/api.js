import { DB } from "./db.js";

const API_BASE = "/api";

let cachedToken = null;

export async function getToken() {
  if (cachedToken) return cachedToken;
  const session = await DB.get("session", "current");
  cachedToken = session ? session.token : null;
  return cachedToken;
}

export async function setSession(token, user) {
  cachedToken = token;
  await DB.put("session", { key: "current", token, user });
}

export async function getCurrentUser() {
  const session = await DB.get("session", "current");
  return session ? session.user : null;
}

export async function clearSession() {
  cachedToken = null;
  await DB.delete("session", "current");
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

class AuthExpiredError extends Error {}

async function request(path, options = {}) {
  const token = await getToken();
  const headers = options.headers || {};

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (e) {
      // ignore
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return null;
  return res.json();
}

// Authenticated binary download (PDF reports, etc). A plain <a href="/api/..."> navigation
// never sends the Authorization header, which is exactly what caused the "Could not validate
// credentials" error on the download button -- so this fetches the file as a blob instead and
// hands the caller a local object URL to trigger the browser's normal save-file flow with.
// `url` is the full path already returned by the server (e.g. "/api/audits/1/report/2/download"),
// not appended to API_BASE again.
async function downloadFile(url) {
  const token = await getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const res = await fetch(url, { headers });

  if (res.status === 401) {
    throw new AuthExpiredError("Session expired");
  }
  if (!res.ok) {
    throw new ApiError(res.statusText, res.status);
  }

  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export const Api = {
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  machineModels: () => request("/catalog/machine-models"),
  machines: (search = "") => request(`/catalog/machines?search=${encodeURIComponent(search)}`),
  auditTypes: () => request("/catalog/audit-types"),
  systemDefs: (auditTypeId) =>
    request(`/catalog/system-defs${auditTypeId ? `?audit_type_id=${auditTypeId}` : ""}`),

  drafts: () => request("/audits/drafts"),
  audit: (id) => request(`/audits/${id}`),

  sync: (audits) => request("/audits/sync", { method: "POST", body: JSON.stringify({ audits }) }),

  uploadAttachment: (auditServerId, formData) =>
    request(`/audits/${auditServerId}/attachments`, { method: "POST", body: formData }),

  generateReport: (auditServerId) => request(`/audits/${auditServerId}/report`, { method: "POST" }),
  downloadReportFile: (downloadUrl) => downloadFile(downloadUrl),

  isOnline: async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
      return res.ok;
    } catch (e) {
      return false;
    }
  },
};

export { ApiError, AuthExpiredError };
