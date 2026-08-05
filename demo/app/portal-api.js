// portal-api.js — fetch helpers for the STUDENT portal only.
//
// Deliberately does not import api.js: the staff app's auth bridge attaches
// the professor/admin principal token (original_principal_token), which must
// never ride along on student /me/* calls. The portal speaks only with the
// student session token, under the same localStorage keys the classic
// demo/student.html uses — the two student surfaces share a session.

const KEYS = {
  token: 'original_session_token',
  studentId: 'original_student_id',
  name: 'original_student_name',
  institution: 'original_institution',
};

export function getSession() {
  try {
    return {
      token: localStorage.getItem(KEYS.token) || '',
      studentId: localStorage.getItem(KEYS.studentId) || '',
      name: localStorage.getItem(KEYS.name) || '',
      institution: localStorage.getItem(KEYS.institution) || '',
    };
  } catch (e) {
    return { token: '', studentId: '', name: '', institution: '' };
  }
}

export function storeSession({ token, student_id, name, institution }) {
  try {
    localStorage.setItem(KEYS.token, token);
    localStorage.setItem(KEYS.studentId, student_id);
    if (name) localStorage.setItem(KEYS.name, name);
    if (institution) localStorage.setItem(KEYS.institution, institution);
  } catch (e) { /* private mode — session just won't persist */ }
}

export function clearSession() {
  try {
    Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
  } catch (e) { /* ignore */ }
}

async function request(path, { method = 'GET', body } = {}) {
  const { token } = getSession();
  const headers = { Accept: 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error(err.detail || `HTTP ${res.status}`);
    e.status = res.status;
    throw e;
  }
  return res.json();
}

export function login(email, institution, name) {
  return request('/student-auth/login', { method: 'POST', body: { email, institution, name } });
}

export function validateSession() {
  return request('/student-auth/me');
}

export function fetchVoice() {
  return request('/me/voice');
}

export function submitWork(text, title) {
  return request('/me/work', { method: 'POST', body: { text, title } });
}

export function advanceFormation() {
  return request('/me/formation/advance', { method: 'POST' });
}
