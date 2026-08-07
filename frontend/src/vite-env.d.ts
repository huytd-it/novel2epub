/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Địa chỉ backend nung sẵn lúc build — đặt trong dashboard Vercel/Cloudflare. */
  readonly N2E_API_BASE?: string;
  /** "tauri" khi build bản desktop (base tương đối). */
  readonly N2E_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
