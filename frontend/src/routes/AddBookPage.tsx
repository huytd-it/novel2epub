import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Page } from "@/app/Shell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Combobox } from "@/components/ui/Combobox";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import {
  useCreateEbook,
  useCreateEbooksBulk,
  usePreviewEbook,
  usePreviewEbooksBulk,
  useTranslateMetadata,
  type BulkCreateItem,
  type BulkEbookResult,
  type BulkPreviewResult,
  type CrawlPreview,
  type EbookCreateResult,
  type EbookPreview,
} from "@/lib/books";
import {
  previewUpload,
  useCreateFromUpload,
  type UploadPreview,
} from "@/lib/upload";
import { useSources, type SourcePreset } from "@/lib/sources";
import { useGlobalAi, useLocalMt, useTranslateDefaults } from "@/lib/settings";

const MAX_BULK_URLS = 20;
const MODES = ["", "fetcher", "stealthy", "dynamic"];

/* ── slug helpers — mirror backend vn_slugify (không fallback "novel") ─────── */

const _VN_MAP: Record<string, string> = (() => {
  const from =
    "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ" +
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ";
  const to =
    "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy" +
    "AAAAAAAAAAAAAAAAADEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYY";
  const m: Record<string, string> = {};
  for (let i = 0; i < from.length; i++) m[from[i]] = to[i];
  return m;
})();

function vnSlugify(value: string): string {
  let s = value
    .split("")
    .map((ch) => _VN_MAP[ch] ?? ch)
    .join("");
  s = s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  s = s.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  if (!s || !/[a-z]/.test(s)) return "";
  return s;
}

function hasLatin(value: string): boolean {
  return /[a-zA-Z]/.test(value);
}

function deriveSlug(title: string): string {
  const s = vnSlugify(title);
  return s;
}

/* ── phát hiện Nguồn theo domain — mirror backend detect_preset (khớp dài nhất
   thắng, hoà thì theo alphabet) để combobox tự điền ngay khi paste link ────── */

function detectSourceName(url: string, presets: SourcePreset[]): string {
  const trimmed = url.trim();
  if (!trimmed) return "";
  let hostname = "";
  try {
    hostname = new URL(trimmed).hostname;
  } catch {
    return "";
  }
  if (!hostname) return "";
  const candidates: [number, string][] = [];
  for (const p of presets) {
    if (!p.domains) continue;
    for (const raw of p.domains.split(",")) {
      const d = raw.trim();
      if (d && hostname.includes(d)) candidates.push([d.length, p.name]);
    }
  }
  if (!candidates.length) return "";
  candidates.sort((a, b) => b[0] - a[0] || a[1].localeCompare(b[1]));
  return candidates[0][1];
}

/* ── small UI ─────────────────────────────────────────────────────────────── */

function FetchToc({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <Checkbox checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5" />
      <span>
        <span className="font-medium">Lấy danh mục ngay</span>
        <span className="mt-0.5 block text-xs opacity-60">Tạo thêm job fetch-toc sau khi lưu truyện.</span>
      </span>
    </label>
  );
}

function SingleResult({ result, reset, extra }: { result: EbookCreateResult; reset: () => void; extra?: string }) {
  return (
    <Panel className="border-success/40 bg-success/5 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Badge tone="celadon">Đã tạo</Badge>
          <h2 className="mt-2 font-display text-lg font-semibold">{result.title || result.slug}</h2>
          <p className="text-xs opacity-60">
            {result.slug}
            {result.toc_job ? " · Đã xếp job lấy mục lục" : ""}
            {extra ? ` · ${extra}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="btn btn-primary btn-sm" to={`/ebooks/${result.slug}`}>
            Mở truyện
          </Link>
          <Button onClick={reset}>Thêm tiếp</Button>
          <Link className="btn btn-sm" to="/">
            Về thư viện
          </Link>
        </div>
      </div>
    </Panel>
  );
}

/* ── JSON beautiful ─────────────────────────────────────────────────────────── */

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function highlightJson(json: string): string {
  const escaped = escapeHtml(json);
  return escaped.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = "text-amber-700 dark:text-amber-300";
      if (/^"/.test(match)) {
        if (/:$/.test(match)) cls = "text-sky-700 dark:text-sky-300 font-medium";
        else cls = "text-emerald-700 dark:text-emerald-300";
      } else if (/true|false/.test(match)) cls = "text-violet-700 dark:text-violet-300";
      else if (/null/.test(match)) cls = "text-pink-700 dark:text-pink-300";
      else cls = "text-orange-700 dark:text-orange-300";
      return `<span class="${cls}">${match}</span>`;
    },
  );
}

function PrettyJson({ data, title = "JSON", defaultOpen = false }: { data: unknown; title?: string; defaultOpen?: boolean }) {
  const [copied, setCopied] = useState(false);
  const jsonStr = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const html = useMemo(() => highlightJson(jsonStr), [jsonStr]);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonStr);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // fallback: no-op
    }
  };

  return (
    <details open={defaultOpen} className="group overflow-hidden rounded-xl border border-base-300 bg-base-100">
      <summary className="flex cursor-pointer list-none items-center justify-between bg-gradient-to-r from-base-200/80 to-base-200/40 px-3 py-2 text-xs font-semibold tracking-wide uppercase">
        <span className="flex items-center gap-2">
          <span className="inline-flex h-2 w-2 rounded-full bg-emerald-400 shadow" />
          {title}
          <span className="rounded bg-base-300 px-1.5 py-0.5 font-mono text-[10px] normal-case tracking-normal opacity-60">
            {jsonStr.length.toLocaleString()} bytes · {jsonStr.split("\n").length} dòng
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="hidden text-[11px] normal-case opacity-60 group-open:inline">Thu gọn</span>
          <span className="text-[11px] normal-case opacity-60 group-open:hidden">Mở rộng</span>
          <span className="text-xs opacity-40">▾</span>
        </span>
      </summary>
      <div className="border-t border-base-300">
        <div className="flex items-center justify-between bg-base-200/40 px-3 py-1.5">
          <span className="font-mono text-[10px] tracking-widest uppercase opacity-50">Preview · beautiful JSON</span>
          <div className="flex items-center gap-2">
            <span className="hidden font-mono text-[10px] opacity-40 sm:inline">UTF-8 · JSON</span>
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                onCopy();
              }}
              className="btn btn-xs h-6 min-h-0 px-2 text-[11px]"
            >
              {copied ? "Đã copy ✓" : "Copy JSON"}
            </button>
          </div>
        </div>
        <div className="relative max-h-[420px] overflow-auto bg-base-100 dark:bg-base-950">
          {/* line numbers + code */}
          <pre className="m-0 p-0 font-mono text-[11.5px] leading-[1.55] text-base-content">
            <code className="block px-3 py-3 whitespace-pre" dangerouslySetInnerHTML={{ __html: html }} />
          </pre>
        </div>
        <div className="bg-base-200/30 px-3 py-1.5 text-[10px] opacity-50">Mẹo: bấm Copy để dán vào Postman / jq; JSON đã format với indent 2.</div>
      </div>
    </details>
  );
}

/* ── Config collapses — 1 card chứa 3 collapse: Nguồn / Dịch / Local MT ────── */

function ConfigCard({
  source,
  crawlPreview,
}: {
  source?: string;
  crawlPreview?: CrawlPreview | null;
}) {
  const sources = useSources();
  const translateDefaults = useTranslateDefaults();
  const globalAi = useGlobalAi();
  const localMt = useLocalMt();

  const preset = useMemo(() => {
    if (!source) return null;
    return sources.data?.presets.find((p) => p.name === source) ?? null;
  }, [sources.data, source]);

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Cấu hình sẽ copy"
        hint={source ? `Nguồn: ${source} · copy config từ preset` : "Tự nhận diện theo domain · fallback mặc định"}
      />
      <div className="divide-y divide-base-300">
        <details open className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-base-200/50">
            <span>Nguồn (Crawl)</span>
            <span className="text-xs opacity-50 group-open:hidden">▶</span>
            <span className="hidden text-xs opacity-50 group-open:inline">▼</span>
          </summary>
          <div className="border-t border-base-300 bg-base-200/30 px-4 py-3 text-xs">
            {preset ? (
              <div className="grid gap-1.5">
                <p>
                  <span className="opacity-60">Preset:</span> {preset.name} · {preset.domains || preset.url || "—"}
                </p>
                <p>
                  <span className="opacity-60">Chế độ:</span> {preset.scrapling_mode} · delay {preset.delay_seconds}s · pattern{" "}
                  <code className="font-mono text-[11px]">{preset.chapter_link_pattern}</code>
                </p>
                {preset.content_selector ? (
                  <p>
                    <span className="opacity-60">content_selector:</span>{" "}
                    <code className="font-mono text-[11px]">{preset.content_selector}</code>
                  </p>
                ) : null}
                {preset.proxy ? (
                  <p>
                    <span className="opacity-60">proxy:</span> {preset.proxy}
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="opacity-60">Chưa chọn preset — sẽ tự nhận diện theo URL hoặc dùng mặc định.</p>
            )}
          <div className="mt-3 mb-4">
            <PrettyJson data={crawlPreview} title="crawl_preview — JSON beautiful" defaultOpen={false} />
          </div>

          </div>
        </details>

        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-base-200/50">
            <span>Dịch (Dịch chung)</span>
            <span className="text-xs opacity-50 group-open:hidden">▶</span>
            <span className="hidden text-xs opacity-50 group-open:inline">▼</span>
          </summary>
          <div className="border-t border-base-300 bg-base-200/30 px-4 py-3 text-xs">
            {translateDefaults.data ? (
              <div className="grid gap-1">
                <p>
                  <span className="opacity-60">type:</span> {translateDefaults.data.type} ·{" "}
                  <span className="opacity-60">genre:</span> {translateDefaults.data.genre} ·{" "}
                  <span className="opacity-60">tone:</span> {translateDefaults.data.tone}
                </p>
                <p>
                  <span className="opacity-60">prompt_max:</span> {translateDefaults.data.prompt_max_chars} ·{" "}
                  <span className="opacity-60">batch:</span> {translateDefaults.data.batch_size} ·{" "}
                  <span className="opacity-60">chunk:</span> {translateDefaults.data.chunk_max_chars}
                </p>
                {globalAi.data ? (
                  <p>
                    <span className="opacity-60">Global AI:</span> {globalAi.data.base_url || "—"} ·{" "}
                    <span className="opacity-60">dịch:</span> {globalAi.data.translation_model || "—"} ·{" "}
                    <span className="opacity-60">trợ lý:</span> {globalAi.data.assistant_model || "—"}
                  </p>
                ) : null}
                <div className="mt-2 mb-4">
                  <PrettyJson data={translateDefaults.data} title="translate_defaults — JSON beautiful" />
                </div>
              </div>
            ) : (
              <p className="opacity-60">Đang tải cấu hình dịch chung…</p>
            )}
          </div>
        </details>

        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-base-200/50">
            <span>Local MT</span>
            <span className="text-xs opacity-50 group-open:hidden">▶</span>
            <span className="hidden text-xs opacity-50 group-open:inline">▼</span>
          </summary>
          <div className="border-t border-base-300 bg-base-200/30 px-4 py-3 text-xs">
            {localMt.data ? (
              <div className="grid gap-1">
                <p>
                  <span className="opacity-60">model:</span> {localMt.data.config.model_key} ·{" "}
                  <span className="opacity-60">backend:</span> {localMt.data.config.backend} ·{" "}
                  <span className="opacity-60">beam:</span> {localMt.data.config.beam_size} ·{" "}
                  <span className="opacity-60">chunk:</span> {localMt.data.config.chunk_mode}
                </p>
                <p className="opacity-60">
                  Engines: {localMt.data.engines.map((e) => `${e.label} (${e.models.filter((m) => m.downloaded).length}/${e.models.length})`).join(" · ")}
                </p>
                <div className="mt-2 mb-4">
                  <PrettyJson data={localMt.data.config} title="local_mt.config — JSON beautiful" />
                </div>
              </div>
            ) : (
              <p className="opacity-60">Đang tải cấu hình Local MT…</p>
            )}
          </div>
        </details>
      </div>
    </Panel>
  );
}

/* ── Dịch meta — cho phép chọn Local MT hoặc models từ Dịch chung ─────────── */

function TranslateMetaControl({
  values,
  onTranslated,
  disabled,
}: {
  values: { title: string; author: string; description: string };
  onTranslated: (patch: { title: string; author: string; description: string }) => void;
  disabled?: boolean;
}) {
  const mutation = useTranslateMetadata();
  const toast = useToast();
  const globalAi = useGlobalAi();
  const [engine, setEngine] = useState<string>("localmt");

  // Build engine options: Local MT + models từ Dịch chung (global_ai)
  const options = useMemo(() => {
    const opts: { value: string; label: string }[] = [{ value: "localmt", label: "Local MT (offline — chỉ dịch y nguyên)" }];
    const t = globalAi.data?.translation_model?.trim();
    const a = globalAi.data?.assistant_model?.trim();
    if (t) opts.push({ value: `ai:${t}`, label: `AI — ${t} (dịch + sinh mô tả)` });
    if (a && a !== t) opts.push({ value: `ai:${a}`, label: `AI — ${a} (dịch + sinh mô tả)` });
    if (!t && !a) opts.push({ value: "ai", label: "AI (mặc định Dịch chung — dịch + sinh mô tả)" });
    return opts;
  }, [globalAi.data]);

  const isAi = engine.startsWith("ai");
  const willEnrich = isAi && !values.description.trim() && !!values.title.trim();

  const translate = async () => {
    const raw = engine.startsWith("ai:") ? engine.slice(3) : engine === "ai" ? "" : "";
    const eng = engine === "localmt" ? "localmt" : "ai";
    try {
      const result = await mutation.mutateAsync({
        title: values.title,
        author: values.author,
        description: values.description,
        engine: eng,
        ...(raw ? { model: raw } : {}),
      });
      // AI có thể "enrich" description ngay cả khi input trống → ưu tiên result
      const nextTitle = (result.title ?? "").trim() || values.title;
      const nextAuthor = (result.author ?? "").trim() || values.author;
      // description: nếu willEnrich thì luôn lấy result.description (dù values rỗng)
      const nextDesc = (result.description ?? "").trim() || values.description;
      onTranslated({ title: nextTitle, author: nextAuthor, description: nextDesc });
      if (willEnrich && nextDesc && !values.description.trim()) {
        toast("AI đã dịch tiêu đề/tác giả và tự viết tóm tắt mô tả từ tiêu đề.", "info");
      }
      if (Object.keys(result.errors ?? {}).length) {
        toast("Dịch có 1 số field lỗi, giữ nguyên bản gốc.", "info");
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), "error");
    }
  };

  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={engine} onChange={(e) => setEngine(e.target.value)} className="min-w-[220px] max-w-[280px]" disabled={disabled}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <Button
          size="sm"
          variant={isAi ? "primary" : "neutral"}
          loading={mutation.isPending}
          disabled={disabled}
          onClick={translate}
          title={isAi ? "AI dựa vào tiêu đề + tác giả để dịch tên và tự viết tóm tắt 2–4 câu nếu mô tả trống" : "Dịch máy cục bộ, không sinh mô tả mới"}
        >
          {isAi ? "Dịch AI + sinh mô tả" : "Dịch meta"}
        </Button>
      </div>
      {isAi ? (
        <p className="text-[11px] leading-relaxed opacity-60">
          {willEnrich ? (
            <>
              <span className="font-medium text-primary">AI sẽ dịch tiêu đề/tác giả và tự viết mô tả 2–4 câu</span> từ tiêu đề
              {values.author.trim() ? ` + tác giả “${values.author.trim()}”` : ""} (mô tả đang trống).
            </>
          ) : values.description.trim() ? (
            <>AI sẽ dịch trọn vẹn tiêu đề, tác giả và mô tả hiện có — không sinh thêm.</>
          ) : (
            <>Nhập tiêu đề (và tác giả nếu có) rồi bấm dịch — AI sẽ dịch tên và tự viết tóm tắt nếu mô tả để trống.</>
          )}
        </p>
      ) : (
        <p className="text-[11px] opacity-50">Local MT chỉ dịch y nguyên các field đã có; không tự sinh mô tả khi trống.</p>
      )}
    </div>
  );
}

export function AddBookPage() {
  const [tab, setTab] = useState<"single" | "bulk" | "upload">("single");
  return (
    <Page title="Thêm truyện" hint="Tạo từ URL mục lục, nhập hàng loạt, hoặc upload file .txt/.epub có sẵn">
      <div role="tablist" className="tabs tabs-box mb-4 w-fit" aria-label="Kiểu nhập truyện">
        <button role="tab" className={`tab ${tab === "single" ? "tab-active" : ""}`} onClick={() => setTab("single")}>
          Nhập 1 link
        </button>
        <button role="tab" className={`tab ${tab === "bulk" ? "tab-active" : ""}`} onClick={() => setTab("bulk")}>
          Nhập hàng loạt
        </button>
        <button role="tab" className={`tab ${tab === "upload" ? "tab-active" : ""}`} onClick={() => setTab("upload")}>
          Upload file
        </button>
      </div>
      {tab === "single" ? <SingleForm /> : tab === "bulk" ? <BulkForm /> : <UploadForm />}
    </Page>
  );
}

function SingleForm() {
  const sources = useSources();
  const previewMutation = usePreviewEbook();
  const createMutation = useCreateEbook();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [source, setSource] = useState("");
  const [sourceTouched, setSourceTouched] = useState(false);
  const [mode, setMode] = useState("");
  const [fetchToc, setFetchToc] = useState(false);
  const [preview, setPreview] = useState<EbookPreview | null>(null);
  const [result, setResult] = useState<EbookCreateResult | null>(null);

  const sourceOptions = useMemo(() => (sources.data?.presets.map((p) => p.name) ?? []), [sources.data]);
  const showError = (error: unknown) => toast(error instanceof Error ? error.message : String(error), "error");

  // Paste link → tự nhận diện Nguồn theo domain trước khi bấm Xem trước, để
  // config hiện đúng nguồn ngay và preview/create gửi source tường minh.
  const detectedSource = useMemo(() => detectSourceName(url, sources.data?.presets ?? []), [url, sources.data]);
  useEffect(() => {
    if (!sourceTouched && detectedSource) setSource(detectedSource);
  }, [detectedSource, sourceTouched]);

  const handleSourceChange = (next: string) => {
    setSource(next);
    setSourceTouched(next.trim() !== "");
  };

  const runPreview = async () => {
    try {
      setPreview(await previewMutation.mutateAsync({ toc_url: url, source, scrapling_mode: mode }));
    } catch (error) {
      showError(error);
    }
  };

  const validateSlug = (slug: string): string | null => {
    if (!slug.trim()) return "Slug trống — hãy dịch tiêu đề hoặc nhập slug có ký tự latin.";
    if (!hasLatin(slug)) return "Slug cần ít nhất 1 ký tự latin (a-z).";
    return null;
  };

  const create = async (withPreview: boolean) => {
    if (withPreview && preview) {
      const err = validateSlug(preview.slug);
      if (err) {
        toast(err, "error");
        return;
      }
    }
    try {
      const metadata = withPreview && preview ? preview : null;
      if (metadata && !metadata.slug.trim()) {
        const derived = deriveSlug(metadata.title);
        if (derived) metadata.slug = derived;
      }
      if (metadata && !hasLatin(metadata.slug)) {
        toast("Slug không có ký tự latin — hãy sửa slug trước khi tạo.", "error");
        return;
      }
      setResult(
        await createMutation.mutateAsync({
          toc_url: url,
          source,
          scrapling_mode: mode,
          fetch_toc: fetchToc,
          ...(metadata ? metadata : {}),
        }),
      );
    } catch (error) {
      showError(error);
    }
  };

  const handleTranslated = (patch: { title: string; author: string; description: string }) => {
    if (!preview) return;
    const nextSlug = deriveSlug(patch.title);
    setPreview({
      ...preview,
      ...patch,
      slug: nextSlug, // để trống nếu không có latin — validate sẽ chặn tạo
    });
    if (!nextSlug) {
      toast("Tiêu đề dịch không tạo được slug latin — hãy nhập slug thủ công.", "info");
    }
  };

  const reset = () => {
    setUrl("");
    setSource("");
    setSourceTouched(false);
    setPreview(null);
    setResult(null);
  };

  if (result) return <SingleResult result={result} reset={reset} />;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,.8fr)]">
      <div className="grid gap-4">
        <Panel>
          <PanelHeader title="Địa chỉ nguồn" hint="Chọn nguồn (search) để copy config; xem trước để duyệt metadata." />
          <div className="grid gap-4 p-4 sm:grid-cols-2">
            <Field label="URL mục lục" className="sm:col-span-2">
              <Input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
            </Field>
            <Field
              label="Nguồn"
              hint={
                source && !sourceTouched
                  ? "Tự nhận diện theo URL — có thể đổi nếu sai."
                  : source
                    ? "Preset này được copy cho ebook mới."
                    : "Tự nhận diện theo domain URL."
              }
            >
              <Combobox value={source} onChange={handleSourceChange} options={sourceOptions} placeholder="Tự động (gõ để tìm nguồn)" />
            </Field>
            <Field label="Chế độ Scrapling">
              <Select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((item) => (
                  <option key={item} value={item}>
                    {item || "Theo nguồn"}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="sm:col-span-2">
              <FetchToc checked={fetchToc} onChange={setFetchToc} />
            </div>
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <Button variant="primary" loading={previewMutation.isPending} disabled={!url.trim()} onClick={runPreview}>
                Xem trước
              </Button>
              <Button loading={createMutation.isPending} disabled={!url.trim()} onClick={() => create(false)}>
                Tạo thẳng
              </Button>
              <Link className="btn btn-ghost btn-sm" to="/">
                Hủy
              </Link>
            </div>
          </div>
        </Panel>

        {/* Config card hiện ngay khi chọn nguồn — trước cả preview */}
        {source ? <ConfigCard source={source} crawlPreview={preview?.crawl_preview ?? null} /> : null}
      </div>

      {preview ? (
        <div className="grid gap-4">
          <Panel>
            <PanelHeader title="Duyệt trước khi tạo" hint={`${preview.chapter_count} chương · Nguồn ${preview.source || "không xác định"} · copy config từ nguồn`} />
            <div className="grid gap-3 p-4">
              {preview.cover_url ? <img src={preview.cover_url} alt="Bìa truyện" className="max-h-48 rounded-box object-cover" /> : null}
              <Field
                label="Slug"
                hint={
                  !preview.slug.trim()
                    ? "Slug trống — cần ký tự latin. Hãy nhập thủ công hoặc dịch lại tiêu đề."
                    : !hasLatin(preview.slug)
                      ? "Slug cần ký tự latin."
                      : undefined
                }
              >
                <Input
                  value={preview.slug}
                  onChange={(e) => setPreview({ ...preview, slug: e.target.value })}
                  placeholder="slug-latin (vd truyen-moi)"
                  className={!preview.slug.trim() || !hasLatin(preview.slug) ? "input-error" : undefined}
                />
              </Field>
              <Field label="Tên truyện">
                <Input value={preview.title} onChange={(e) => setPreview({ ...preview, title: e.target.value })} />
              </Field>
              <Field label="Tác giả">
                <Input value={preview.author} onChange={(e) => setPreview({ ...preview, author: e.target.value })} />
              </Field>
              <Field label="URL bìa">
                <Input value={preview.cover_url} onChange={(e) => setPreview({ ...preview, cover_url: e.target.value })} />
              </Field>
              <Field label="Mô tả">
                <Textarea rows={5} value={preview.description} onChange={(e) => setPreview({ ...preview, description: e.target.value })} />
              </Field>
              <TranslateMetaControl
                values={{ title: preview.title, author: preview.author, description: preview.description }}
                onTranslated={handleTranslated}
                disabled={!preview.title.trim()}
              />
              <p className="text-[11px] opacity-60">Dịch meta sẽ tự cập nhật slug từ tiêu đề mới; nếu không có ký tự latin thì để trống để bạn nhập tay.</p>
              <div className="mb-4">
                <PrettyJson data={preview} title="Preview JSON — beautiful" defaultOpen={false} />
              </div>
              <Button
                variant="primary"
                loading={createMutation.isPending}
                disabled={!preview.slug.trim() || !hasLatin(preview.slug)}
                onClick={() => create(true)}
                title={!preview.slug.trim() || !hasLatin(preview.slug) ? "Slug cần ký tự latin" : undefined}
              >
                Tạo truyện đã duyệt
              </Button>
              {!preview.slug.trim() || !hasLatin(preview.slug) ? (
                <p className="text-xs text-error">Slug không hợp lệ — cần ít nhất 1 ký tự latin trước khi tạo.</p>
              ) : null}
            </div>
          </Panel>
          <ConfigCard source={preview.source} crawlPreview={preview.crawl_preview} />
        </div>
      ) : (
        <Panel className="hidden place-items-center p-8 text-center text-sm opacity-55 xl:grid">
          Metadata và cấu hình crawl sẽ hiện ở đây sau khi xem trước. Chọn nguồn phía trái để xem config được copy.
        </Panel>
      )}
    </div>
  );
}

/* ── Upload file .txt/.epub → tạo ebook từ chương raw ────────────────────── */

function UploadForm() {
  const toast = useToast();
  const createMutation = useCreateFromUpload();
  const [file, setFile] = useState<File | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [form, setForm] = useState({ slug: "", title: "", author: "", description: "" });
  const [result, setResult] = useState<(EbookCreateResult & { chapter_count: number }) | null>(null);
  const showError = (error: unknown) => toast(error instanceof Error ? error.message : String(error), "error");

  const pick = async (next: File | null) => {
    setFile(next);
    setPreview(null);
    setResult(null);
    if (!next) return;
    if (!/\.(txt|epub)$/i.test(next.name)) {
      toast("Chỉ chấp nhận file .txt và .epub.", "error");
      return;
    }
    setPreviewing(true);
    try {
      const p = await previewUpload(next);
      setPreview(p);
      setForm({ slug: p.slug, title: p.title, author: p.author, description: "" });
      if (!p.slug) toast("Không gợi ý được slug latin từ file — hãy nhập slug thủ công.", "info");
    } catch (error) {
      showError(error);
    } finally {
      setPreviewing(false);
    }
  };

  const handleTranslated = (patch: { title: string; author: string; description: string }) => {
    const nextSlug = deriveSlug(patch.title);
    setForm((current) => ({ ...current, ...patch, slug: nextSlug }));
    if (!nextSlug) toast("Tiêu đề dịch không tạo được slug latin — hãy nhập slug thủ công.", "info");
  };

  const create = async () => {
    if (!file) return;
    const slug = form.slug.trim() || deriveSlug(form.title);
    if (!slug.trim() || !hasLatin(slug)) {
      toast("Slug không hợp lệ — cần ít nhất 1 ký tự latin.", "error");
      return;
    }
    try {
      const created = await createMutation.mutateAsync({ file, meta: { ...form, slug } });
      setResult({ status: "created", slug: created.slug, title: created.title, source: "", toc_job: null, chapter_count: created.chapter_count });
      toast(`Đã tạo truyện với ${created.chapter_count} chương raw.`);
    } catch (error) {
      showError(error);
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setForm({ slug: "", title: "", author: "", description: "" });
    setResult(null);
  };

  if (result) {
    return <SingleResult result={result} reset={reset} extra={`${result.chapter_count} chương raw`} />;
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,.8fr)]">
      <div className="grid gap-4">
        <Panel>
          <PanelHeader title="File nguồn" hint="Mỗi lần 1 file .txt (nhiều chương) hoặc .epub — chương raw đi tiếp qua dịch/biên tập/build như luồng crawl." />
          <div className="grid gap-4 p-4">
            <Field label="Chọn file" hint="TXT tách chương theo tiêu đề (Chương N / Chapter N / 第N章) · EPUB tách theo file con, giữ ảnh bìa.">
              <input
                type="file"
                accept=".txt,.epub"
                className="file-input file-input-sm w-full"
                onChange={(e) => pick(e.target.files?.[0] ?? null)}
              />
            </Field>
            {previewing ? <p className="text-sm opacity-60">Đang đọc file…</p> : null}
            {preview ? (
              <div className="grid gap-1 text-sm">
                <p>
                  <Badge tone="gold">{preview.chapter_count} chương</Badge>{" "}
                  {preview.has_cover ? <Badge tone="celadon">Có bìa</Badge> : null}
                </p>
                <p className="text-xs opacity-60">{preview.filename}</p>
                {preview.chapters_preview.length ? (
                  <ol className="mt-1 max-h-56 list-decimal overflow-auto rounded-box border border-base-300 bg-base-200/30 px-3 py-2 pl-8 text-xs">
                    {preview.chapters_preview.map((title, index) => (
                      <li key={index} className="truncate py-0.5" title={title}>
                        {title || <span className="opacity-50">(không tiêu đề)</span>}
                      </li>
                    ))}
                    {preview.chapter_count > preview.chapters_preview.length ? (
                      <li className="opacity-50">…và {preview.chapter_count - preview.chapters_preview.length} chương nữa</li>
                    ) : null}
                  </ol>
                ) : null}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" loading={createMutation.isPending} disabled={!preview || !form.slug.trim() || !hasLatin(form.slug)} onClick={create}>
                Tạo truyện từ file
              </Button>
              <Link className="btn btn-ghost btn-sm" to="/">
                Hủy
              </Link>
            </div>
          </div>
        </Panel>
      </div>

      {preview ? (
        <div className="grid gap-4">
          <Panel>
            <PanelHeader title="Duyệt trước khi tạo" hint={`${preview.chapter_count} chương · toc_url để trống, có thể điền sau để crawl bổ sung`} />
            <div className="grid gap-3 p-4">
              <Field
                label="Slug"
                hint={
                  !form.slug.trim()
                    ? "Slug trống — cần ký tự latin. Hãy nhập thủ công."
                    : !hasLatin(form.slug)
                      ? "Slug cần ký tự latin."
                      : undefined
                }
              >
                <Input
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  placeholder="slug-latin (vd truyen-moi)"
                  className={!form.slug.trim() || !hasLatin(form.slug) ? "input-error" : undefined}
                />
              </Field>
              <Field label="Tên truyện">
                <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Tác giả">
                <Input value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })} />
              </Field>
              <Field label="Mô tả">
                <Textarea rows={5} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <TranslateMetaControl
                values={{ title: form.title, author: form.author, description: form.description }}
                onTranslated={handleTranslated}
                disabled={!form.title.trim()}
              />
            </div>
          </Panel>
        </div>
      ) : (
        <Panel className="hidden place-items-center p-8 text-center text-sm opacity-55 xl:grid">
          Chọn file .txt/.epub để xem trước metadata và danh sách chương trước khi tạo.
        </Panel>
      )}
    </div>
  );
}

function BulkPreviewItem({
  item,
  onUpdate,
  onTranslated,
}: {
  item: BulkPreviewResult;
  onUpdate: (patch: Partial<BulkPreviewResult>) => void;
  onTranslated: (patch: { title: string; author: string; description: string }) => void;
}) {
  const handleTranslated = (patch: { title: string; author: string; description: string }) => {
    onTranslated(patch);
  };

  if (item.status === "failed") {
    return (
      <div className="flex items-start justify-between gap-3 border-b border-base-300 p-3">
        <div className="min-w-0">
          <Badge tone="vermilion">Lỗi</Badge>
          <p className="mt-1 truncate text-xs" title={item.url}>
            {item.url}
          </p>
          {item.reason ? <p className="mt-1 text-xs text-error">{item.reason}</p> : null}
          <p className="mt-1 text-[11px] opacity-50">Bỏ qua hoặc kiểm tra lại URL — URL này sẽ được backend thử lại khi tạo.</p>
        </div>
      </div>
    );
  }
  const slugInvalid = !item.slug?.trim() || !hasLatin(item.slug ?? "");
  return (
    <div className="grid gap-3 border-b border-base-300 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge tone="gold">{item.chapter_count ?? 0} chương</Badge>
          {item.source ? <span className="badge badge-ghost badge-xs">{item.source}</span> : null}
          <p className="truncate text-xs opacity-60" title={item.url}>
            {item.url}
          </p>
        </div>
        <TranslateMetaControl
          values={{ title: item.title ?? "", author: item.author ?? "", description: item.description ?? "" }}
          onTranslated={handleTranslated}
          disabled={!item.title}
        />
      </div>
      <Field label="Tên truyện">
        <Input value={item.title ?? ""} onChange={(e) => onUpdate({ title: e.target.value })} />
      </Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Tác giả">
          <Input value={item.author ?? ""} onChange={(e) => onUpdate({ author: e.target.value })} />
        </Field>
        <Field label="Slug" hint={slugInvalid ? "Cần ký tự latin — để trống sẽ bị chặn khi tạo" : undefined}>
          <Input
            value={item.slug ?? ""}
            onChange={(e) => onUpdate({ slug: e.target.value })}
            placeholder="slug-latin"
            className={slugInvalid ? "input-error" : undefined}
          />
        </Field>
      </div>
      <Field label="Mô tả">
        <Textarea rows={2} value={item.description ?? ""} onChange={(e) => onUpdate({ description: e.target.value })} />
      </Field>
      <div className="mb-4">
        <PrettyJson data={item} title="Item preview — JSON beautiful" />
      </div>
      {/* 1 card chứa 3 collapse cho từng truyện hàng loạt */}
      <ConfigCard source={item.source} crawlPreview={item.crawl_preview as CrawlPreview | null} />
    </div>
  );
}

function BulkForm() {
  const previewMutation = usePreviewEbooksBulk();
  const createMutation = useCreateEbooksBulk();
  const toast = useToast();
  const [text, setText] = useState("");
  const [fetchToc, setFetchToc] = useState(false);
  const [previews, setPreviews] = useState<BulkPreviewResult[] | null>(null);
  const [results, setResults] = useState<BulkEbookResult[]>([]);
  const urls = text.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
  const showResults = results.length > 0;

  const updatePreview = (index: number, patch: Partial<BulkPreviewResult>) => {
    setPreviews((current) => current?.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)) ?? null);
  };

  const runPreview = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setPreviews((await previewMutation.mutateAsync({ toc_urls: urls })).results);
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), "error");
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    // validate slugs have latin before submit
    const invalid = (previews ?? []).filter((item) => item.status === "ok" && item.title?.trim() && (!item.slug?.trim() || !hasLatin(item.slug ?? "")));
    if (invalid.length) {
      toast(`Có ${invalid.length} truyện slug thiếu ký tự latin — hãy sửa trước khi tạo.`, "error");
      return;
    }
    const items: BulkCreateItem[] = (previews ?? [])
      .filter((item) => item.status === "ok" && item.title?.trim())
      .map((item) => ({
        url: item.url,
        slug: item.slug,
        title: item.title,
        author: item.author,
        description: item.description,
        cover_url: item.cover_url,
        source: item.source,
        scrapling_mode: item.scrapling_mode,
      }));
    try {
      setResults((await createMutation.mutateAsync({ toc_urls: urls, items, fetch_toc: fetchToc })).results);
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), "error");
    }
  };

  // Bulk translation handler — also auto-update slug
  const handleBulkTranslated = (index: number, patch: { title: string; author: string; description: string }) => {
    const nextSlug = deriveSlug(patch.title);
    updatePreview(index, { ...patch, slug: nextSlug });
    if (!nextSlug) {
      toast("Tiêu đề dịch không tạo được slug latin — hãy nhập tay.", "info");
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,.9fr)]">
      <Panel>
        <form onSubmit={submit} className="grid gap-4 p-4">
          <Field label="URL mục lục" hint={`${urls.length}/${MAX_BULK_URLS} URL · Nguồn được tự nhận diện riêng cho từng dòng.`}>
            <Textarea
              rows={12}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setPreviews(null);
                setResults([]);
              }}
              placeholder={"https://.../truyen-a\nhttps://.../truyen-b"}
            />
          </Field>
          <FetchToc checked={fetchToc} onChange={setFetchToc} />
          {urls.length > MAX_BULK_URLS ? (
            <p role="alert" className="text-sm text-error">
              Vượt quá giới hạn {MAX_BULK_URLS} URL.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="neutral" loading={previewMutation.isPending} disabled={!urls.length || urls.length > MAX_BULK_URLS} onClick={runPreview}>
              Xem trước
            </Button>
            <Button type="submit" variant="primary" loading={createMutation.isPending} disabled={!urls.length || urls.length > MAX_BULK_URLS}>
              Tạo {urls.length || ""} truyện{previews ? " đã duyệt" : ""}
            </Button>
            <Link className="btn btn-ghost btn-sm" to="/">
              Về thư viện
            </Link>
          </div>
        </form>
      </Panel>
      <Panel aria-live="polite">
        <PanelHeader
          title={showResults ? "Kết quả" : previews ? "Duyệt trước khi tạo" : "Preview"}
          hint={
            showResults
              ? `${results.filter((item) => item.status === "created").length} truyện đã tạo`
              : previews
                ? "Mỗi card là 1 truyện — chứa 3 collapse Nguồn/Dịch/Local MT. Sửa metadata rồi bấm Tạo."
                : "Xem trước để duyệt/sửa metadata từng URL — mỗi card chứa cấu hình copy từ nguồn."
          }
        />
        <div className="divide-y divide-base-300">
          {showResults ? (
            results.map((item, index) => (
              <div key={`${item.url}-${index}`} className="flex items-start justify-between gap-3 p-3">
                <div className="min-w-0">
                  <Badge tone={item.status === "created" ? "celadon" : item.status === "failed" ? "vermilion" : "gold"}>
                    {item.status === "created" ? "Đã tạo" : item.status === "failed" ? "Lỗi" : "Đã tồn tại"}
                  </Badge>
                  <p className="mt-1 truncate text-xs" title={item.url}>
                    {item.url}
                  </p>
                  {item.reason ? <p className="mt-1 text-xs text-error">{item.reason}</p> : null}
                </div>
                {item.slug ? (
                  <Link className="btn btn-xs" to={`/ebooks/${item.slug}`}>
                    Mở
                  </Link>
                ) : null}
              </div>
            ))
          ) : previews ? (
            previews.map((item, index) => (
              <BulkPreviewItem
                key={`${item.url}-${index}`}
                item={item}
                onUpdate={(patch) => updatePreview(index, patch)}
                onTranslated={(patch) => handleBulkTranslated(index, patch)}
              />
            ))
          ) : (
            <p className="p-8 text-center text-sm opacity-55">Bấm Xem trước để duyệt metadata từng URL — mỗi URL xử lý độc lập.</p>
          )}
        </div>
      </Panel>
    </div>
  );
}
