import { useEffect, useState } from "react";
import clsx from "clsx";

import { apiUrl } from "@/lib/api";
import { useAiProviders, useDeleteAiProvider, useSaveAiProvider } from "@/lib/aiProviders";
import { Field, Input, Select } from "@/components/ui/Field";
import { Combobox } from "@/components/ui/Combobox";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { IconPlus, IconTrash } from "@/components/icons";

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

/** Ô base_url + preset provider dùng lại (name → base_url, lưu trong DB, dùng
 * chung mọi truyện): chọn từ danh sách để điền base_url thay vì gõ tay, vẫn
 * gõ tay được bình thường cho URL chưa lưu preset. */
export function ProviderPickerField({
  label,
  hint,
  value,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const { data } = useAiProviders();
  const presets = data?.presets ?? [];
  const save = useSaveAiProvider();
  const del = useDeleteAiProvider();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");

  const matched = presets.find((p) => p.base_url === value.trim());

  const onPick = (name: string) => {
    const preset = presets.find((p) => p.name === name);
    if (preset) onChange(preset.base_url);
  };

  const onSaveCurrent = () => {
    const name = newName.trim();
    if (!name) return;
    save.mutate(
      { name, base_url: value },
      {
        onSuccess: () => {
          toast(`Đã lưu provider "${name}".`);
          setAdding(false);
          setNewName("");
        },
        onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
      },
    );
  };

  const onDeleteMatched = () => {
    if (!matched) return;
    del.mutate(matched.name, {
      onSuccess: () => toast(`Đã xóa provider "${matched.name}".`),
      onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
    });
  };

  return (
    <Field label={label} hint={hint}>
      <div className="flex flex-col gap-1.5">
        <div className="join w-full">
          <Select
            className="join-item w-36 shrink-0"
            disabled={disabled}
            value={matched?.name ?? ""}
            onChange={(e) => onPick(e.target.value)}
          >
            <option value="">— provider đã lưu —</option>
            {presets.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </Select>
          <Input
            type="text"
            className="join-item min-w-0 flex-1"
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
            placeholder="https://host/v1"
          />
          {matched ? (
            <Button
              size="sm"
              variant="ghost"
              className="join-item shrink-0"
              disabled={disabled || del.isPending}
              onClick={onDeleteMatched}
              title={`Xóa provider đã lưu "${matched.name}"`}
            >
              <IconTrash size={12} />
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              className="join-item shrink-0"
              disabled={disabled || !value.trim()}
              onClick={() => setAdding((v) => !v)}
              title="Lưu base_url hiện tại làm provider mới"
            >
              <IconPlus size={12} />
            </Button>
          )}
        </div>
        {adding ? (
          <div className="join w-full">
            <Input
              autoFocus
              type="text"
              className="join-item min-w-0 flex-1"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Tên provider, vd: OpenRouter"
              spellCheck={false}
            />
            <Button
              size="sm"
              variant="primary"
              className="join-item shrink-0"
              loading={save.isPending}
              disabled={!newName.trim()}
              onClick={onSaveCurrent}
            >
              Lưu
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="join-item shrink-0"
              onClick={() => {
                setAdding(false);
                setNewName("");
              }}
            >
              Hủy
            </Button>
          </div>
        ) : null}
      </div>
    </Field>
  );
}
