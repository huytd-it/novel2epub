import { useEffect, useState } from "react";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { apiUrl } from "@/lib/api";
import { ago } from "@/lib/format";
import {
  EMPTY_PRESET,
  useClonePreset,
  useDeletePreset,
  useSavePreset,
  useSources,
  useTestPreset,
  type SourcePreset,
} from "@/lib/sources";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { Checkbox, Field, Input, InputWithIcon, Select, Textarea } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconExternal, IconPlus, IconSearch, IconTrash } from "@/components/icons";

/* ── Đặc tả field cho form preset ─────────────────────────────────────── */

type Kind = "text" | "textarea" | "number" | "checkbox" | "select";

interface FieldSpec {
  key: keyof SourcePreset & string;
  label: string;
  kind: Kind;
  hint?: string;
  options?: { value: string; label: string }[];
  wide?: boolean;
  step?: number;
}

const BASIC_FIELDS: FieldSpec[] = [
  { key: "url", label: "URL trang chủ / mục lục mẫu", kind: "text", wide: true },
  { key: "domains", label: "Domain nhận diện (phẩy)", kind: "text", hint: "vd: 69shuba.com,69shu.com" },
  {
    key: "scrapling_mode",
    label: "Chế độ crawl",
    kind: "select",
    options: [
      { value: "fetcher", label: "fetcher (nhanh nhất)" },
      { value: "stealthy", label: "stealthy" },
      { value: "dynamic", label: "dynamic (render JS)" },
    ],
  },
  { key: "chapter_link_pattern", label: "Regex link chương", kind: "text" },
];

const SELECTOR_FIELDS: FieldSpec[] = [
  { key: "toc_selector", label: "Selector mục lục (link chương)", kind: "text" },
  { key: "content_selector", label: "Selector nội dung chương", kind: "text" },
  { key: "chapter_title_selector", label: "Selector tiêu đề chương", kind: "text" },
  { key: "title_selector", label: "Selector tên truyện", kind: "text" },
  { key: "author_selector", label: "Selector tác giả", kind: "text" },
  { key: "desc_selector", label: "Selector mô tả", kind: "text" },
  { key: "cover_selector", label: "Selector ảnh bìa", kind: "text" },
  { key: "next_page_selector", label: "Selector trang kế (nội dung)", kind: "text" },
  { key: "next_page_url_pattern", label: "Regex URL trang kế", kind: "text" },
  { key: "max_pages_per_chapter", label: "Số trang tối đa / chương", kind: "number" },
  { key: "toc_next_page_selector", label: "Selector trang kế (mục lục)", kind: "text" },
  { key: "toc_max_pages", label: "Số trang mục lục tối đa", kind: "number" },
];

const CRAWL_FIELDS: FieldSpec[] = [
  { key: "delay_seconds", label: "Delay giữa request (giây)", kind: "number", step: 0.1 },
  { key: "concurrency_cap", label: "Trần song song", kind: "number", hint: "0 = mặc định theo chế độ" },
  { key: "impersonate", label: "Impersonate (fingerprint)", kind: "text" },
  { key: "proxy", label: "Proxy", kind: "text", hint: "http://... hoặc socks5://host:port" },
  { key: "user_agent", label: "User-Agent tùy chỉnh", kind: "text" },
  { key: "encoding", label: "Encoding trang (nếu không phải UTF-8)", kind: "text" },
  { key: "headless", label: "Chạy headless", kind: "checkbox" },
  { key: "magic", label: "magic (scrapling auto-fix)", kind: "checkbox" },
  { key: "solve_cloudflare", label: "Giải Cloudflare challenge", kind: "checkbox" },
  { key: "network_idle", label: "Đợi mạng nhàn rỗi", kind: "checkbox" },
  { key: "dns_over_https", label: "DNS-over-HTTPS", kind: "checkbox" },
  { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
  { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
  { key: "retry_backoff", label: "Hệ số backoff", kind: "number", step: 0.1 },
  { key: "retry_max_delay_seconds", label: "Delay thử lại tối đa (giây)", kind: "number" },
  { key: "retry_respect_retry_after", label: "Tôn trọng header Retry-After", kind: "checkbox" },
  { key: "js_code", label: "JS chạy sau khi tải trang", kind: "textarea", wide: true },
  { key: "strip_patterns", label: "Regex loại bỏ nội dung thừa (1 dòng / pattern)", kind: "textarea", wide: true },
];

function FieldControl({
  spec,
  value,
  onChange,
}: {
  spec: FieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (spec.kind === "checkbox") {
    return (
      <label className="flex items-center gap-2 py-1 text-[13px]">
        <Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {spec.label}
      </label>
    );
  }
  if (spec.kind === "select") {
    return (
      <Field label={spec.label} hint={spec.hint}>
        <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {(spec.options ?? []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
    );
  }
  if (spec.kind === "textarea") {
    const text = Array.isArray(value) ? value.join("\n") : String(value ?? "");
    return (
      <Field label={spec.label} hint={spec.hint}>
        <Textarea value={text} onChange={(e) => onChange(e.target.value)} rows={4} className="font-mono text-xs" />
      </Field>
    );
  }
  if (spec.kind === "number") {
    return (
      <Field label={spec.label} hint={spec.hint}>
        <Input
          type="number"
          step={spec.step ?? 1}
          value={String(value ?? 0)}
          onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
        />
      </Field>
    );
  }
  return (
    <Field label={spec.label} hint={spec.hint}>
      <Input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} spellCheck={false} />
    </Field>
  );
}

function FieldGroup({ title, fields, draft, onChange }: { title: string; fields: FieldSpec[]; draft: SourcePreset; onChange: (k: string, v: unknown) => void }) {
  return (
    <fieldset className="rounded-box border border-base-300 p-3">
      <legend className="px-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</legend>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {fields.map((spec) => (
          <div key={spec.key} className={clsx(spec.wide && "md:col-span-2")}>
            <FieldControl spec={spec} value={draft[spec.key]} onChange={(v) => onChange(spec.key, v)} />
          </div>
        ))}
      </div>
    </fieldset>
  );
}

/* ── Modal thêm / sửa preset ─────────────────────────────────────────── */

function PresetModal({
  open,
  onClose,
  preset,
}: {
  open: boolean;
  onClose: () => void;
  preset: SourcePreset | null; // null = tạo mới
}) {
  const [name, setName] = useState("");
  const [draft, setDraft] = useState<SourcePreset>(EMPTY_PRESET);
  const save = useSavePreset();
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setName(preset?.name ?? "");
      setDraft(preset ?? EMPTY_PRESET);
    }
  }, [open, preset]);

  const set = (k: string, v: unknown) => setDraft((prev) => ({ ...prev, [k]: v }));

  const submit = () => {
    if (!name.trim()) {
      toast("Cần tên nguồn.", "error");
      return;
    }
    const strip = draft.strip_patterns;
    save.mutate(
      {
        ...draft,
        name: name.trim(),
        strip_patterns: typeof strip === "string" ? (strip as unknown as string).split("\n").map((s) => s.trim()).filter(Boolean) : strip,
      },
      {
        onSuccess: () => {
          toast(preset ? "Đã cập nhật nguồn." : "Đã tạo nguồn.");
          onClose();
        },
        onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={preset ? `Sửa nguồn — ${preset.name}` : "Thêm nguồn"}
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {preset ? "Lưu" : "Tạo nguồn"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field label="Tên nguồn" hint="Định danh duy nhất, ebook tham chiếu bằng tên này">
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={Boolean(preset)} className="w-full" />
        </Field>
        <FieldGroup title="Cơ bản" fields={BASIC_FIELDS} draft={draft} onChange={set} />
        <FieldGroup title="Selector" fields={SELECTOR_FIELDS} draft={draft} onChange={set} />
        <FieldGroup title="Crawl nâng cao" fields={CRAWL_FIELDS} draft={draft} onChange={set} />
      </div>
    </Modal>
  );
}

/* ── Modal test dry-run ──────────────────────────────────────────────── */

function TestModal({ open, onClose, name }: { open: boolean; onClose: () => void; name: string }) {
  const [tocUrl, setTocUrl] = useState("");
  const test = useTestPreset();
  const toast = useToast();

  useEffect(() => {
    if (open) setTocUrl("");
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Test nguồn — ${name}`}
      footer={
        <>
          <Button onClick={onClose}>Đóng</Button>
          <Button
            variant="primary"
            loading={test.isPending}
            onClick={() =>
              test.mutate(
                { name, tocUrl },
                {
                  onSuccess: () => {
                    toast("Đang test — kết quả hiện lại ở thẻ nguồn sau vài giây.");
                    onClose();
                  },
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                },
              )
            }
          >
            Chạy test
          </Button>
        </>
      }
    >
      <p className="mb-2 text-xs opacity-60">
        Dry-run: đọc mục lục + 1 chương mẫu, không ghi gì xuống đĩa. Chạy nền, kết quả lưu lại trên thẻ nguồn.
      </p>
      <Field label="URL mục lục để test">
        <Input autoFocus value={tocUrl} onChange={(e) => setTocUrl(e.target.value)} className="w-full" spellCheck={false} />
      </Field>
    </Modal>
  );
}

/* ── Thẻ preset ──────────────────────────────────────────────────────── */

function PresetCard({
  preset,
  usage,
  validation,
  onEdit,
  onTest,
}: {
  preset: SourcePreset;
  usage: string[];
  validation: { ok: boolean; message: string; checked_at: number } | undefined;
  onEdit: () => void;
  onTest: () => void;
}) {
  const del = useDeletePreset();
  const clone = useClonePreset();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <Panel className="p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[15px] font-semibold">{preset.name}</h3>
          <p className="truncate text-xs opacity-60">{preset.domains || preset.url || "—"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {validation ? (
            <Badge tone={validation.ok ? "celadon" : "vermilion"} className="cursor-help" >
              <span title={validation.message}>{validation.ok ? "test OK" : "test lỗi"}</span>
            </Badge>
          ) : null}
          {usage.length > 0 ? <Badge tone="indigo">{usage.length} truyện đang dùng</Badge> : null}
        </div>
      </div>

      {validation ? (
        <p data-numeric className="mb-2 text-[11px] opacity-50">
          {ago(validation.checked_at)} · {validation.message}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" variant="primary" onClick={onEdit}>
          Sửa
        </Button>
        <Button size="sm" onClick={onTest}>
          Test
        </Button>
        <Button
          size="sm"
          loading={clone.isPending}
          onClick={() =>
            clone.mutate(
              { name: preset.name, newName: "" },
              {
                onSuccess: (res) => toast(`Đã nhân bản thành "${res.name}".`),
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              },
            )
          }
        >
          Nhân bản
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon={<IconTrash size={12} />}
          disabled={usage.length > 0}
          title={usage.length > 0 ? `Đang dùng bởi: ${usage.join(", ")}` : undefined}
          onClick={() => setConfirmDelete(true)}
        >
          Xóa
        </Button>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() =>
          del.mutate(preset.name, {
            onSuccess: () => setConfirmDelete(false),
            onError: (err) => {
              setConfirmDelete(false);
              toast(err instanceof Error ? err.message : String(err), "error");
            },
          })
        }
        title="Xóa nguồn"
        body={`Xóa nguồn "${preset.name}"? Không thể hoàn tác.`}
        confirmLabel="Xóa"
        destructive
        pending={del.isPending}
      />
    </Panel>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function SourcesPage() {
  const { data, isPending } = useSources();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<SourcePreset | null | undefined>(undefined); // undefined = đóng
  const [testing, setTesting] = useState<string | null>(null);

  const presets = (data?.presets ?? []).filter((p) => {
    const q = search.trim().toLowerCase();
    return !q || p.name.toLowerCase().includes(q) || p.domains.toLowerCase().includes(q);
  });

  return (
    <Page
      title="Nguồn"
      hint="Preset crawl dùng lại cho nhiều truyện — selector, chế độ crawl, delay, proxy"
      actions={
        <>
          <InputWithIcon
            icon={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm theo tên / domain"
            className="w-56"
          />
          <a href={apiUrl("/sources/export")} className="btn btn-sm inline-flex items-center gap-1.5">
            Xuất YAML <IconExternal size={12} />
          </a>
          <Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setEditing(null)}>
            Thêm nguồn
          </Button>
        </>
      }
    >
      {isPending ? (
        <Loading label="Đang tải nguồn" />
      ) : presets.length === 0 ? (
        <Panel>
          <EmptyState
            title={search ? "Không có nguồn nào khớp" : "Chưa có nguồn nào"}
            hint={search ? "Thử từ khóa khác." : 'Bấm "Thêm nguồn" để tạo preset crawl đầu tiên.'}
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {presets.map((p) => (
            <PresetCard
              key={p.name}
              preset={p}
              usage={data?.usage[p.name] ?? []}
              validation={data?.validation[p.name]}
              onEdit={() => setEditing(p)}
              onTest={() => setTesting(p.name)}
            />
          ))}
        </div>
      )}

      <PresetModal open={editing !== undefined} onClose={() => setEditing(undefined)} preset={editing ?? null} />
      {testing ? <TestModal open onClose={() => setTesting(null)} name={testing} /> : null}
    </Page>
  );
}
