/**
 * Lớp gọi HTTP dùng chung.
 *
 * Bản web chạy cùng origin với FastAPI nên base rỗng là đủ. Bản Tauri nạp
 * bundle từ `tauri://` — không có origin nào để suy ra server — nên base và
 * token phải đọc từ cấu hình người dùng nhập trong app.
 */

const BASE_KEY = "n2e-api-base";
const TOKEN_KEY = "n2e-api-token";

/** Địa chỉ nung sẵn lúc build (Vercel/Cloudflare Pages), rỗng cho bản web. */
const BUILT_IN_BASE = (import.meta.env.N2E_API_BASE ?? "").replace(/\/+$/, "");

export function apiBase(): string {
  // Giá trị người dùng nhập ở trang Kết nối luôn thắng: cùng một bundle có thể
  // được trỏ sang máy khác mà không cần build lại.
  const saved = (localStorage.getItem(BASE_KEY) ?? "").replace(/\/+$/, "");
  return saved || BUILT_IN_BASE;
}

/** Base mặc định lúc build, để trang Kết nối cho biết đang trỏ đi đâu. */
export function builtInApiBase(): string {
  return BUILT_IN_BASE;
}

export function setApiBase(value: string) {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (trimmed) localStorage.setItem(BASE_KEY, trimmed);
  else localStorage.removeItem(BASE_KEY);
}

export function apiToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setApiToken(value: string) {
  const trimmed = value.trim();
  if (trimmed) localStorage.setItem(TOKEN_KEY, trimmed);
  else localStorage.removeItem(TOKEN_KEY);
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type Options = Omit<RequestInit, "body"> & { body?: unknown; form?: Record<string, unknown> };

async function readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return `${res.status} ${res.statusText}`;
  try {
    const data = JSON.parse(text) as { detail?: unknown; error?: unknown };
    const detail = data.detail ?? data.error;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    /* phản hồi không phải JSON — dùng nguyên văn bên dưới */
  }
  return text.slice(0, 400);
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, form, headers, ...rest } = options;
  const init: RequestInit = { ...rest, headers: { ...headers } };
  const h = init.headers as Record<string, string>;

  const token = apiToken();
  if (token) h.Authorization = `Bearer ${token}`;

  if (form !== undefined) {
    // Nhiều route hiện có nhận Form(...) chứ không phải JSON body.
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(form)) {
      if (value === undefined || value === null) continue;
      if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)));
      else params.append(key, String(value));
    }
    init.body = params;
    h["Content-Type"] = "application/x-www-form-urlencoded";
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    h["Content-Type"] = "application/json";
  }

  const res = await fetch(apiUrl(path), init);
  if (!res.ok) throw new ApiError(res.status, await readError(res));
  if (res.status === 204) return undefined as T;

  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as T;
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>(path, { ...init, method: "GET" }),
  post: <T>(path: string, options: Options = {}) => request<T>(path, { ...options, method: "POST" }),
  patch: <T>(path: string, options: Options = {}) => request<T>(path, { ...options, method: "PATCH" }),
  del: <T>(path: string, options: Options = {}) => request<T>(path, { ...options, method: "DELETE" }),
};
