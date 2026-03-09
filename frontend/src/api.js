const API_BASE = (process.env.REACT_APP_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const toQueryString = (params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
};

const request = async (path, { method = "GET", body, headers } = {}) => {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    const error = new Error((data && data.error) || `Request failed (${res.status})`);
    error.status = res.status;
    error.payload = data;
    throw error;
  }

  return data;
};

export const api = {
  listSessions: () => request("/api/sessions/"),
  createSession: (name) =>
    request("/api/session/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  deleteSession: (name) =>
    request(`/api/session/${encodeURIComponent(name)}/`, { method: "DELETE" }),
  listHistory: (session) => request(`/api/history/${toQueryString({ session })}`),
  listPdfs: (session) => request(`/api/pdfs/${toQueryString({ session })}`),
  listMetrics: () => request("/api/metrics/summary/"),
  uploadPdf: (formData) =>
    request("/api/upload/", {
      method: "POST",
      body: formData,
    }),
  ask: (payload) =>
    request("/api/ask/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deletePdf: (payload) =>
    request("/api/delete/", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  retryDocument: (documentId) =>
    request(`/api/documents/${documentId}/retry/`, { method: "POST" }),
  getDocumentPageText: (documentId, page) =>
    request(`/api/documents/${documentId}/page-text/${toQueryString({ page })}`),
  searchExternal: ({ q, source }) =>
    request(`/api/search/external/${toQueryString({ q, source })}`),
  importExternal: (payload) =>
    request("/api/import/external/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listHighlights: (documentId) =>
    request(`/api/highlights/${toQueryString({ document_id: documentId })}`),
  createHighlight: (payload) =>
    request("/api/highlights/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteHighlight: (highlightId) =>
    request(`/api/highlights/${highlightId}/`, { method: "DELETE" }),
  searchHighlights: ({ session, q }) =>
    request(`/api/highlights/search/${toQueryString({ session, q })}`),
};

export { API_BASE };
