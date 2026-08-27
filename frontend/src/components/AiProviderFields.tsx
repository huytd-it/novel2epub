import { useEffect, useState } from "react";
import clsx from "clsx";

import { apiUrl } from "@/lib/api";
import { Field } from "@/components/ui/Field";
import { Combobox } from "@/components/ui/Combobox";

const MODELS_CACHE_KEY = "n2e-models-cache";
const MODELS_UPDATED_EVENT = "n2e:models-updated";

function readModelsCache(): Record<string, string[]> {
  try {
    return JSON.parse(localStorage.getItem(MODELS_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeModelsCache(cache: Record<string, string[]>) {
  try {
    localStorage.setItem(MODELS_CACHE_KEY, JSON.stringify(cache));
  } catch {
    /* localStorage không có sẵn (private mode) — bỏ qua */
  }
}

/** Tải model từ {base_url}/models, merge vào cache theo base_url rồi báo cho mọi
 * Combobox model đang mở nạp lại. Trả {count, total, error?}. */
export async function fetchAndMergeModels(
  baseUrl: string,
  apiKey: string,
): Promise<{ count: number; total: number; error?: string }> {
  const url = (baseUrl ?? "").trim();
  if (!url) return { count: 0, total: 0, error: "Nhập base_url trước." };
  try {
    const resp = await fetch(apiUrl("/settings/ai/models"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: url, api_key: apiKey.trim() }),
    });
    const data = (await resp.json()) as { models?: string[]; error?: string };
    if (data.error) return { count: 0, total: 0, error: `Lỗi: ${data.error}` };
    const fresh = data.models ?? [];
    const cache = readModelsCache();
    const existing = Array.isArray(cache[url]) ? cache[url] : [];
    const merged = Array.from(new Set(existing.concat(fresh)));
    cache[url] = merged;
    writeModelsCache(cache);
    window.dispatchEvent(new CustomEvent(MODELS_UPDATED_EVENT, { detail: url }));
    return { count: fresh.length, total: merged.length };
  } catch (e) {
    return { count: 0, total: 0, error: `Lỗi: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/** Nạp models đã cache cho một base_url (rỗng nếu chưa có). */
function cachedModelsFor(baseUrl: string): string[] {
  const url = (baseUrl ?? "").trim();
  if (!url) return [];
  const cached = readModelsCache()[url];
  return Array.isArray(cached) ? cached : [];
}

/** Ô model: combobox đọc từ cache theo base_url, tự nạp lại khi có models mới. */
export function ModelField({
  label,
  hint,
  value,
  baseUrl,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  baseUrl: string;
  disabled?: boolean;
  onChange: (next: unknown) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    const url = (baseUrl ?? "").trim();
    const cached = cachedModelsFor(url);
    setModels(cached);
    setStatus(cached.length ? `Đã nạp ${cached.length} model từ cache.` : "");
  }, [baseUrl]);

  useEffect(() => {
    const onUpdated = (e: Event) => {
      const url = (e as CustomEvent<string>).detail;
      if (url === (baseUrl ?? "").trim()) {
        const cached = cachedModelsFor(url);
        setModels(cached);
        setStatus(cached.length ? `Đã nạp ${cached.length} model từ cache.` : "");
      }
    };
    window.addEventListener(MODELS_UPDATED_EVENT, onUpdated);
    return () => window.removeEventListener(MODELS_UPDATED_EVENT, onUpdated);
  }, [baseUrl]);

  return (
    <Field label={label} hint={hint}>
      <Combobox
        value={value}
        onChange={(v: string) => onChange(v)}
        options={models}
        placeholder="Chọn model..."
        disabled={disabled}
      />
      {status ? <span className={clsx("block text-xs italic opacity-60")}>{status}</span> : null}
    </Field>
  );
}
