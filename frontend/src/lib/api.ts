// My-Trade backend REST client.
// All data flows through this single client. No secrets are ever stored in the
// browser. Base URL is read from VITE_API_BASE_URL with a sensible localhost
// fallback for local development.

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(init.headers || {}),
      },
    });
  } catch (err: any) {
    throw new ApiError(
      `Cannot reach My-Trade backend at ${API_BASE_URL}. Is the bot API running?`,
      0,
      { cause: String(err) },
    );
  }

  const text = await res.text();
  const body = text ? safeParse(text) : null;
  if (!res.ok) {
    const msg =
      (body && typeof body === "object" && (body as any).detail) ||
      `Request failed: ${res.status} ${res.statusText}`;
    throw new ApiError(String(msg), res.status, body);
  }
  return body as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) =>
    request<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T,>(p: string, body?: unknown) =>
    request<T>(p, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
};
