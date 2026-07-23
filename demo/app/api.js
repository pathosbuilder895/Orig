// api.js — minimal fetch helpers for the Original API (same origin).
//
// Auth bridge (ADR-003 parity): attach a principal token when one is present
// in localStorage; the zero-login demo has none → demo principal, unchanged.
// This mirrors the shim in demo/professor.html so the app works identically in
// the demo and behind real auth.

const API_BASE = ''; // same origin as the page

function authHeaders(extra) {
  const headers = { Accept: 'application/json', ...extra };
  try {
    const tok = localStorage.getItem('original_principal_token');
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
  } catch (e) { /* localStorage unavailable — demo principal */ }
  return headers;
}

export async function getJSON(path) {
  const res = await fetch(API_BASE + path, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

// Fetch several paths, tolerating individual failures (returns null for those).
export function getJSONSafe(path) {
  return getJSON(path).catch(() => null);
}

// POST with a JSON body. On failure, surfaces the API's {detail: "..."}
// message when present (matches the error contract demo/professor.html relies on).
export async function postJSON(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${path} → HTTP ${res.status}`);
  }
  return res.json();
}

// POST multipart form data (file uploads). No Content-Type header — the
// browser must set it itself to include the multipart boundary.
export async function postForm(path, formData) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${path} → HTTP ${res.status}`);
  }
  return res.json();
}
