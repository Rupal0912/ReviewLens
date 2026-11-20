// All requests go to our own backend. No LLM key or LLM URL exists in the browser.
async function request(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const uploadCsv = (file) => {
  const form = new FormData();
  form.append("file", file);
  return request("/api/upload", { method: "POST", body: form });
};
export const getLatest = () => request("/api/dashboard/latest");
export const suggestReply = (rowId) => request(`/api/reviews/${rowId}/reply`, { method: "POST" });
