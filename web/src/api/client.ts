import type { StudentList, StudentStateResponse, TokenResponse, UserResponse } from "./types";

const ACCESS = "original_access_token";
const REFRESH = "original_refresh_token";

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS);
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH);
}

export function setTokens(tokens: TokenResponse): void {
  sessionStorage.setItem(ACCESS, tokens.access_token);
  sessionStorage.setItem(REFRESH, tokens.refresh_token);
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS);
  sessionStorage.removeItem(REFRESH);
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string | Array<{ msg: string }> };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]?.msg) return j.detail[0].msg;
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

async function refreshAccess(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return false;
  const res = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) {
    clearTokens();
    return false;
  }
  const data = (await res.json()) as TokenResponse;
  setTokens(data);
  return true;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  retry = true
): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && retry && getRefreshToken()) {
    const ok = await refreshAccess();
    if (ok) return apiFetch(path, init, false);
  }
  return res;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as TokenResponse;
  setTokens(data);
}

export async function fetchMe(): Promise<UserResponse> {
  const res = await apiFetch("/api/v1/auth/me");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<UserResponse>;
}

export async function fetchStudents(): Promise<StudentList> {
  const res = await apiFetch("/api/v1/students/");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<StudentList>;
}

export async function fetchStudentState(studentId: string): Promise<StudentStateResponse> {
  const res = await apiFetch(`/api/v1/students/${studentId}/state`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<StudentStateResponse>;
}
