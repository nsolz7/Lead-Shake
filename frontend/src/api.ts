const API_ROOT = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  // Auth rides in an HttpOnly session cookie (set by the server on login),
  // so no token ever touches JS-accessible storage.
  const response = await fetch(`${API_ROOT}${path}`, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail ?? message; } catch { /* response was not JSON */ }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  return api<{ username: string }>("/auth/login", {
    method: "POST", body: JSON.stringify({ username, password }),
  });
}

export async function logout() {
  try { await api("/auth/logout", { method: "POST" }); } catch { /* already signed out */ }
}

/** Only allow http(s) targets for externally sourced URLs (blocks javascript: etc.). */
export function safeHref(url: unknown): string | undefined {
  if (typeof url !== "string" || !url) return undefined;
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

export async function downloadExport(id: string) {
  const response = await fetch(`${API_ROOT}/exports/${id}/download`, { credentials: "same-origin" });
  if (!response.ok) throw new ApiError(response.status, "Export download failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `lead-evidence-${id}.zip`;
  anchor.click();
  URL.revokeObjectURL(url);
}
