import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import {
  useAiProviders,
  useDeleteAiProvider,
  useSaveAiProvider,
  type AiProviderPreset,
} from "@/lib/aiProviders";
import { useGlobalAi } from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { SkeletonTable } from "@/components/ui/Loading";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, InputWithIcon } from "@/components/ui/Field";
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
  const save = useSaveAiProvider();
  const del = useDeleteAiProvider();
  const toast = useToast();
  const editing = preset !== null;

  useEffect(() => {
    if (open) {
      setName(preset?.name ?? "");
      setBaseUrl(preset?.base_url ?? "");
    }
  }, [open, preset]);

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
        <Field label="Tên" hint="Tên gợi nhớ để chọn nhanh ở ô Base URL (Dịch chung / AI từng truyện)">
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="vd: OpenRouter"
            spellCheck={false}
            className="w-full"
          />
        </Field>
        <Field label="Base URL" hint="Endpoint OpenAI-compatible, vd: https://openrouter.ai/api/v1">
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://host/v1"
            spellCheck={false}
            className="w-full font-mono text-xs"
          />
        </Field>
      </div>
    </Modal>
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
