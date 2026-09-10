const TOKEN_KEY = "lm_token";
const USER_KEY = "lm_user";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "/api";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): any | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}

export function storeSession(token: string, user: any) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request(
  path: string,
  options: RequestInit = {}
): Promise<any> {
  const token = getToken();

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (
    options.body &&
    !(options.body instanceof FormData)
  ) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearSession();
    window.location.href = "/login/inspector";
    throw new ApiError(
      401,
      "Session expired. Please log in again."
    );
  }

  const text = await res.text();

  let data: any = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    const message =
      data?.detail ||
      (typeof data === "string"
        ? data
        : "Request failed") ||
      `Request failed (${res.status})`;

    throw new ApiError(res.status, message);
  }

  return data;
}

export const api = {
  get: (p: string) => request(p),

  post: (p: string, body?: any) =>
    request(p, {
      method: "POST",
      body:
        body === undefined
          ? undefined
          : JSON.stringify(body),
    }),

  patch: (p: string, body?: any) =>
    request(p, {
      method: "PATCH",
      body:
        body === undefined
          ? undefined
          : JSON.stringify(body),
    }),

  del: (p: string) =>
    request(p, {
      method: "DELETE",
    }),

  upload: (p: string, form: FormData) =>
    request(p, {
      method: "POST",
      body: form,
    }),
};

export function fmtDate(
  iso?: string | null
): string {
  if (!iso) return "—";

  const d = new Date(iso);

  if (isNaN(d.getTime())) return "—";

  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function fmtDateTime(
  iso?: string | null
): string {
  if (!iso) return "—";

  const d = new Date(iso);

  if (isNaN(d.getTime())) return "—";

  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fileUrl(
  imageId: number
): string {
  // The backend accepts the JWT via query param so plain <img> tags
  // (which cannot send an Authorization header) can load protected images.

  const token = getToken();

  const path = `/images/${imageId}/file`;

  return token
    ? `${API_BASE_URL}${path}?token=${encodeURIComponent(token)}`
    : `${API_BASE_URL}${path}`;
}