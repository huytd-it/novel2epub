import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import {
  useAiProviders,
  useDeleteAiProvider,
  useSaveAiProvider,
  type AiProviderPreset,
} from "@/lib/aiProviders";
import { useGlobalAi, useSaveGlobalAi } from "@/lib/settings";
import { fetchAndMergeModels, ModelField } from "@/components/AiProviderFields";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { SkeletonTable } from "@/components/ui/Loading";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, InputWithIcon, Select } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconPlus, IconSearch } from "@/components/icons";

type TestState =
  | { status: "idle" }
  | { status: "testing" }
  | { status: "ok"; latency_ms?: number; model_count?: number }
  | { status: "error"; error: string };

function validateBaseUrl(value: string): string {
  const t = value.trim();
  if (!t) return "Nhập base_url.";
  if (!/^https?:\/\/\S+$/.test(t)) return "base_url phải dạng http(s)://host... (vd: https://openrouter.ai/api/v1).";
  return "";
}

/* ── Mẫu provider (chọn nhanh khi thêm) ─────────────────────────────────── */

type ProviderTemplateId = "openai" | "claude" | "chat2api" | "custom";

interface ProviderTemplate {
  id: ProviderTemplateId;
  label: string;
  name: string;
  base_url: string;
  placeholder: string;
  baseUrlHint: string;
  modelExample: string;
  apiKeyHint: string;
  exampleCurl?: string;
}

const PROVIDER_TEMPLATES: Record<ProviderTemplateId, ProviderTemplate> = {
  openai: {
    id: "openai",
    label: "1 — OpenAI",
    name: "OpenAI",
    base_url: "https://api.openai.com/v1",
    placeholder: "https://api.openai.com/v1",
    baseUrlHint: "Endpoint OpenAI chính thức.",
    modelExample: "gpt-4o-mini",
    apiKeyHint: "Lấy key tại platform.openai.com — điền ở ô API key (Dịch chung / AI từng truyện).",
  },
  claude: {
    id: "claude",
    label: "2 — Claude",
    name: "Claude",
    base_url: "https://api.anthropic.com/v1",
    placeholder: "https://api.anthropic.com/v1",
    baseUrlHint: "Endpoint Anthropic native.",
    modelExample: "claude-sonnet-4-20250514",
    apiKeyHint:
      "Anthropic native khác chuẩn OpenAI-compatible — nếu báo lỗi kết nối, dùng gateway OpenAI-compatible (vd: OpenRouter) với model anthropic/claude-sonnet-4.",
  },
  chat2api: {
    id: "chat2api",
    label: "3 — Chat2API",
    name: "chat2api",
    base_url: "http://127.0.0.1:8100/v1",
    placeholder: "http://127.0.0.1:8100/v1",
    baseUrlHint: "chat2api local — backend OpenAI-compatible, model dạng <provider>/<model>.",
    modelExample: "qwen-web/qwen3.7-plus",
    apiKeyHint:
      "Không đặt key = server mở. Có đặt CHAT2API_KEYS / api_key thì gửi Authorization: Bearer <key>. Giữ hội thoại bằng header X-Chat2api-Session-Id.",
    exampleCurl: `curl http://127.0.0.1:8100/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $KEY" \\
  -H "X-Chat2api-Session-Id: my-conv-01" \\
  -d '{"model":"qwen-web/qwen3.7-plus","messages":[{"role":"user","content":"Xin chào"}]}'`,
  },
  custom: {
    id: "custom",
    label: "4 — Custom",
    name: "",
    base_url: "",
    placeholder: "https://host/v1",
    baseUrlHint: "Endpoint OpenAI-compatible bất kỳ, vd: https://openrouter.ai/api/v1",
    modelExample: "",
    apiKeyHint: "Điền API key tương ứng ở ô API key khi cấu hình Dịch/AI.",
  },
};

const TEMPLATE_IDS: ProviderTemplateId[] = ["openai", "claude", "chat2api", "custom"];

function guessTemplate(baseUrl: string): ProviderTemplateId {
  const u = baseUrl.trim().toLowerCase();
  if (!u) return "custom";
  if (u.includes("127.0.0.1:8100") || u.includes("localhost:8100")) return "chat2api";
  if (u.includes("api.openai.com")) return "openai";
  if (u.includes("api.anthropic.com")) return "claude";
  return "custom";
}

/* ── Modal thêm / sửa provider ───────────────────────────────────────── */

function ProviderModal({
  open,
  onClose,
  preset,
  existingNames,
}: {
  open: boolean;
  onClose: () => void;
  preset: AiProviderPreset | null;
  existingNames: Set<string>;
}) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [template, setTemplate] = useState<ProviderTemplateId>("chat2api");
  const save = useSaveAiProvider();
  const del = useDeleteAiProvider();
  const toast = useToast();
  const editing = preset !== null;
  const active = PROVIDER_TEMPLATES[template];

  useEffect(() => {
    if (open) {
      setName(preset?.name ?? PROVIDER_TEMPLATES.chat2api.name);
      setBaseUrl(preset?.base_url ?? PROVIDER_TEMPLATES.chat2api.base_url);
      setTemplate(preset ? guessTemplate(preset.base_url) : "chat2api");
    }
  }, [open, preset]);

  const pickTemplate = (id: ProviderTemplateId) => {
    setTemplate(id);
    if (id === "custom") return;
    const t = PROVIDER_TEMPLATES[id];
    setName(t.name);
    setBaseUrl(t.base_url);
  };

  const submit = () => {
    const cleanName = name.trim();
    const cleanUrl = baseUrl.trim();
    if (!cleanName) {
      toast("Nhập tên provider.", "error");
      return;
    }
    const urlErr = validateBaseUrl(cleanUrl);
    if (urlErr) {
      toast(urlErr, "error");
      return;
    }
    // Đổi tên = lưu tên mới rồi xóa tên cũ (backend upsert theo name).
    if (editing && cleanName !== preset.name) {
      if (existingNames.has(cleanName)) {
        toast(`Tên "${cleanName}" đã tồn tại.`, "error");
        return;
      }
      save.mutate(
        { name: cleanName, base_url: cleanUrl },
        {
          onSuccess: () =>
            del.mutate(preset.name, {
              onSuccess: () => {
                toast(`Đã đổi tên "${preset.name}" → "${cleanName}".`);
                onClose();
              },
              onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
            }),
          onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
        },
      );
      return;
    }
    if (!editing && existingNames.has(cleanName)) {
      toast(`Tên "${cleanName}" đã tồn tại — mở Sửa ở dòng đó để đổi base_url.`, "error");
      return;
    }
    save.mutate(
      { name: cleanName, base_url: cleanUrl },
      {
        onSuccess: () => {
          toast(editing ? "Đã lưu provider." : `Đã thêm provider "${cleanName}".`);
          onClose();
        },
        onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Sửa provider "${preset.name}"` : "Thêm provider"}
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={save.isPending || del.isPending} onClick={submit}>
            {editing ? "Lưu" : "Thêm"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <Field label="Mẫu provider" hint="Chọn mẫu để điền sẵn Tên + Base URL, vẫn sửa tay được.">
          <Select value={template} onChange={(e) => pickTemplate(e.target.value as ProviderTemplateId)}>
            {TEMPLATE_IDS.map((id) => (
              <option key={id} value={id}>
                {PROVIDER_TEMPLATES[id].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Tên" hint="Tên gợi nhớ để chọn nhanh ở ô Base URL (Dịch chung / AI từng truyện)">
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={active.name ? `vd: ${active.name}` : "vd: OpenRouter"}
            spellCheck={false}
            className="w-full"
          />
        </Field>
        <Field label="Base URL" hint={active.baseUrlHint}>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={active.placeholder}
            spellCheck={false}
            className="w-full font-mono text-xs"
          />
        </Field>
        <div className="rounded-lg border border-base-300 bg-base-200/50 p-2.5 text-xs leading-relaxed">
          <p className="text-[11px] font-semibold tracking-wide uppercase opacity-60">Ví dụ</p>
          <p className="mt-1">
            <span className="opacity-60">Base URL: </span>
            <code className="font-mono text-[11px] break-all">{active.base_url || active.placeholder}</code>
          </p>
          {active.modelExample ? (
            <p className="mt-0.5">
              <span className="opacity-60">Model: </span>
              <code className="font-mono text-[11px] break-all">{active.modelExample}</code>
              {template === "chat2api" ? (
                <span className="opacity-60"> (lấy id nguyên dạng &lt;provider&gt;/&lt;model&gt; từ GET /v1/models, vd combo/my-combo)</span>
              ) : null}
            </p>
          ) : null}
          <p className="mt-0.5 opacity-80">{active.apiKeyHint}</p>
          {template === "chat2api" ? (
            <>
              <p className="mt-1 opacity-60">
                Liệt kê model: <code className="font-mono text-[11px]">GET /v1/models</code> với header{" "}
                <code className="font-mono text-[11px]">Authorization: Bearer $KEY</code>
              </p>
              {active.exampleCurl ? (
                <pre className="mt-1 overflow-x-auto rounded bg-base-300/50 p-2 font-mono text-[11px] whitespace-pre">
                  {active.exampleCurl}
                </pre>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

/* ── Provider & model mặc định chung ──────────────────────────────────── */

function DefaultProviderPanel({ presets }: { presets: AiProviderPreset[] }) {
  const toast = useToast();
  const client = useQueryClient();
  const { data: globalAi, isPending } = useGlobalAi();
  const save = useSaveGlobalAi();
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [modelsLoading, setModelsLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (globalAi && !initialized) {
      setBaseUrl(globalAi.base_url);
      setModel(globalAi.assistant_model);
      setInitialized(true);
    }
  }, [globalAi, initialized]);

  const matched = presets.find((p) => p.base_url === baseUrl.trim());
  const customInUse = globalAi != null && baseUrl.trim() !== "" && !matched;
  const dirty =
    globalAi != null && (baseUrl !== globalAi.base_url || model !== globalAi.assistant_model);

  const onPick = (name: string) => {
    const preset = presets.find((p) => p.name === name);
    if (preset) setBaseUrl(preset.base_url);
  };

  const refreshModels = async () => {
    setModelsLoading(true);
    try {
      const res = await fetchAndMergeModels(baseUrl, "");
      toast(res.error ?? `Đã nạp ${res.count} model mới (tổng ${res.total}).`, res.error ? "error" : "ok");
    } finally {
      setModelsLoading(false);
    }
  };

  const onSave = () => {
    if (!globalAi) return;
    if (!baseUrl.trim()) {
      toast("Chọn provider mặc định.", "error");
      return;
    }
    save.mutate(
      { ...globalAi, api_key: "", base_url: baseUrl.trim(), assistant_model: model.trim() },
      {
        onSuccess: () => {
          toast("Đã lưu provider & model mặc định.");
          // Thread trợ lý mới nạp mặc định từ ai.openai (global) — làm mới cache.
          client.invalidateQueries({ queryKey: ["assistant-defaults"] });
        },
        onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
      },
    );
  };

  return (
    <Panel className="mb-4 overflow-hidden">
      <PanelHeader
        title="Provider & model mặc định"
        hint="Base URL + model trợ lý dùng chung toàn hệ thống — thread trợ lý mới và truyện chưa có cấu hình riêng đều dùng giá trị này"
        actions={
          <>
            <Button size="sm" variant="ghost" loading={modelsLoading} onClick={refreshModels}>
              Tải models
            </Button>
            <Button size="sm" variant="primary" loading={save.isPending} disabled={!dirty} onClick={onSave}>
              Lưu mặc định
            </Button>
          </>
        }
      />
      <div className="grid gap-4 p-4 md:grid-cols-2">
        {isPending || !globalAi ? (
          <p className="text-[13px] opacity-60 md:col-span-2">Đang đọc cấu hình Global AI…</p>
        ) : (
          <>
            <Field
              label="Provider mặc định"
              hint="Chọn từ danh sách đã lưu — đặt Base URL chung (Dịch chung / AI từng truyện / trợ lý)"
            >
              <Select value={matched?.name ?? ""} onChange={(e) => onPick(e.target.value)}>
                <option value="">— chọn provider —</option>
                {presets.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </Select>
              {matched ? (
                <span className="mt-1 block truncate font-mono text-xs opacity-60" title={matched.base_url}>
                  {matched.base_url}
                </span>
              ) : customInUse ? (
                <span className="mt-1 block text-xs text-warning">
                  Đang dùng URL tùy chỉnh (không có trong danh sách): {baseUrl} — chọn preset để thay.
                </span>
              ) : null}
            </Field>
            <ModelField
              label="Model trợ lý mặc định"
              hint="Panel Trợ lý, glossary, rewrite, cleanup, Reader và metadata AI dùng model này khi chưa có cấu hình riêng"
              value={model}
              baseUrl={baseUrl}
              onChange={(v) => setModel(String(v ?? ""))}
            />
          </>
        )}
      </div>
    </Panel>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function AiProvidersPage() {
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AiProviderPreset | null>(null);
  const [deleting, setDeleting] = useState<AiProviderPreset | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [testingAll, setTestingAll] = useState(false);
  const toast = useToast();

  const { data, isPending } = useAiProviders();
  const { data: globalAi } = useGlobalAi();
  const del = useDeleteAiProvider();

  const presets = useMemo(() => data?.presets ?? [], [data]);
  const existingNames = useMemo(() => new Set(presets.map((p) => p.name)), [presets]);
  const globalBaseUrl = (globalAi?.base_url ?? "").trim();

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return presets;
    return presets.filter(
      (p) => p.name.toLowerCase().includes(needle) || p.base_url.toLowerCase().includes(needle),
    );
  }, [presets, search]);

  const runTest = async (preset: AiProviderPreset) => {
    setTests((prev) => ({ ...prev, [preset.name]: { status: "testing" } }));
    try {
      const r = await api.post<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string }>(
        "/settings/ai/test",
        { body: { base_url: preset.base_url, api_key: "", timeout_seconds: 15 } },
      );
      setTests((prev) => ({
        ...prev,
        [preset.name]: r.ok
          ? { status: "ok", latency_ms: r.latency_ms, model_count: r.model_count }
          : { status: "error", error: r.error || "Kết nối thất bại." },
      }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [preset.name]: { status: "error", error: e instanceof Error ? e.message : String(e) },
      }));
    }
  };

  const runTestAll = async () => {
    setTestingAll(true);
    try {
      for (const p of rows) {
        // eslint-disable-next-line no-await-in-loop -- test nối tiếp để khỏi dội endpoint
        await runTest(p);
      }
    } finally {
      setTestingAll(false);
    }
  };

  const openAdd = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (preset: AiProviderPreset) => {
    setEditing(preset);
    setModalOpen(true);
  };

  return (
    <Page
      title="Provider AI"
      hint="Endpoint OpenAI-compatible dùng lại — chọn nhanh ở ô Base URL thay vì gõ tay. API key không lưu theo provider."
      actions={
        <>
          <InputWithIcon
            icon={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm tên / base_url"
            className="w-56"
          />
          <Button
            size="sm"
            disabled={rows.length === 0 || testingAll}
            loading={testingAll}
            onClick={runTestAll}
            title="Gọi GET /models từng provider để kiểm tra kết nối"
          >
            Thử tất cả
          </Button>
          <Button icon={<IconPlus size={14} />} variant="primary" onClick={openAdd}>
            Thêm provider
          </Button>
        </>
      }
    >
      <DefaultProviderPanel presets={presets} />

      <Panel className="overflow-hidden">
        <PanelHeader
          title="Danh sách provider"
          hint={`${rows.length} mục${globalBaseUrl ? ` · Global AI đang dùng: ${globalBaseUrl}` : ""}`}
        />
        {isPending ? (
          <SkeletonTable rows={4} cols={3} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={search ? "Không có provider nào khớp" : "Chưa có provider nào"}
            hint={search ? "Thử từ khóa khác." : 'Bấm "Thêm provider" để lưu endpoint đầu tiên.'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  <th className="px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                    Tên
                  </th>
                  <th className="px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                    Base URL
                  </th>
                  <th className="px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                    Trạng thái
                  </th>
                  <th className="w-52 px-3 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const t = tests[p.name] ?? { status: "idle" as const };
                  const inUse = globalBaseUrl !== "" && p.base_url === globalBaseUrl;
                  return (
                    <tr key={p.name} className="border-b border-base-300 last:border-b-0">
                      <td className="px-3 py-2 align-top">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-[13px] font-medium">{p.name}</span>
                          {inUse ? (
                            <Badge tone="celadon" className="text-[10px]">
                              Global AI
                            </Badge>
                          ) : null}
                        </div>
                      </td>
                      <td className="max-w-md px-3 py-2 align-top">
                        <span className="block truncate font-mono text-xs opacity-80" title={p.base_url}>
                          {p.base_url}
                        </span>
                      </td>
                      <td className="px-3 py-2 align-top text-xs">
                        {t.status === "testing" ? (
                          <span className="opacity-60">Đang thử…</span>
                        ) : t.status === "ok" ? (
                          <span className="text-success">
                            OK{t.model_count !== undefined ? ` · ${t.model_count} model` : ""}
                            {t.latency_ms !== undefined ? ` · ${t.latency_ms}ms` : ""}
                          </span>
                        ) : t.status === "error" ? (
                          <span className="text-error" title={t.error}>
                            Lỗi: {t.error.length > 80 ? `${t.error.slice(0, 80)}…` : t.error}
                          </span>
                        ) : (
                          <span className="opacity-40">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right align-top">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            disabled={t.status === "testing" || testingAll}
                            onClick={() => runTest(p)}
                            className={clsx("btn btn-ghost btn-xs", (t.status === "testing" || testingAll) && "btn-disabled")}
                          >
                            Thử
                          </button>
                          <button type="button" onClick={() => openEdit(p)} className="btn btn-ghost btn-xs">
                            Sửa
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleting(p)}
                            className="btn btn-ghost btn-xs text-error"
                          >
                            Xóa
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <ProviderModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        preset={editing}
        existingNames={existingNames}
      />
      <ConfirmDialog
        open={deleting !== null}
        onCancel={() => setDeleting(null)}
        onConfirm={() =>
          deleting &&
          del.mutate(deleting.name, {
            onSuccess: () => {
              toast(`Đã xóa provider "${deleting.name}".`);
              setDeleting(null);
            },
            onError: (e) => toast(e instanceof Error ? e.message : String(e), "error"),
          })
        }
        title="Xóa provider"
        body={
          deleting
            ? `Xóa provider "${deleting.name}"? Các chỗ đang dùng base_url này (Dịch chung / AI từng truyện) giữ nguyên URL đã điền, chỉ mất shortcut chọn nhanh.`
            : ""
        }
        confirmLabel="Xóa"
        destructive
        pending={del.isPending}
      />
    </Page>
  );
}
