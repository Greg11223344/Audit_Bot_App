import { t } from "./i18n.js";

const API_BASE = "/api";

export function getToken() {
  return localStorage.getItem("admin_token");
}

export function getUser() {
  const raw = localStorage.getItem("admin_user");
  return raw ? JSON.parse(raw) : null;
}

export function setSession(token, user) {
  localStorage.setItem("admin_token", token);
  localStorage.setItem("admin_user", JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem("admin_token");
  localStorage.removeItem("admin_user");
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const token = getToken();
  const headers = options.headers || {};

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearSession();
    alert(t("sessionExpired"));
    location.hash = "#/login";
  }

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

// Authenticated binary download (PDF reports). A plain <a href="/api/..."> navigation never
// sends the Authorization header, which is what caused the "Could not validate credentials"
// error -- so this fetches the file as a blob and hands back a local object URL instead.
// `url` is the full path already returned by the server, not appended to API_BASE again.
async function downloadFile(url) {
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  const res = await fetch(url, { headers });

  if (res.status === 401) {
    clearSession();
    alert(t("sessionExpired"));
    location.hash = "#/login";
    throw new ApiError("Session expired", 401);
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

  kpis: () => request("/dashboard/kpis"),

  audits: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/audits${qs ? "?" + qs : ""}`);
  },
  audit: (id) => request(`/audits/${id}`),
  deleteAudit: (id) => request(`/audits/${id}`, { method: "DELETE" }),
  generateReport: (id) => request(`/audits/${id}/report`, { method: "POST" }),
  downloadReportFile: (downloadUrl) => downloadFile(downloadUrl),

  tasks: (status) => request(`/tasks${status ? "?status=" + status : ""}`),
  updateTask: (id, payload) => request(`/tasks/${id}`, { method: "PUT", body: JSON.stringify(payload) }),

  machineModels: () => request("/catalog/machine-models"),
  createMachineModel: (name) => request("/catalog/machine-models", { method: "POST", body: JSON.stringify({ name }) }),

  machines: (search = "") => request(`/catalog/machines?search=${encodeURIComponent(search)}`),
  createMachine: (payload) => request("/catalog/machines", { method: "POST", body: JSON.stringify(payload) }),
  updateMachine: (id, payload) => request(`/catalog/machines/${id}`, { method: "PUT", body: JSON.stringify(payload) }),

  auditTypes: () => request("/catalog/audit-types"),
  systemDefs: (auditTypeId, { includeInactive = false } = {}) => {
    const qs = new URLSearchParams();
    if (auditTypeId) qs.set("audit_type_id", auditTypeId);
    if (includeInactive) qs.set("include_inactive", "true");
    const q = qs.toString();
    return request(`/catalog/system-defs${q ? "?" + q : ""}`);
  },
  createSystemDef: (payload) => request("/catalog/system-defs", { method: "POST", body: JSON.stringify(payload) }),

  users: () => request("/catalog/users"),
  createUser: (payload) => request("/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (id, payload) => request(`/users/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
};

export { ApiError };
