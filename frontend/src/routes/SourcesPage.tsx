import { useEffect, useMemo, useState, type ReactNode } from "react";
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
import {
  DomInspector,
  RegexField,
  SelectorField,
  extractImageUrls,
} from "@/components/CrawlSelectorLab";
import { api } from "@/lib/api";

type DomSnapshot = { html: string; sampleLinks: string[]; url: string };

const DOM_CACHE_KEY = "n2e:domLab:v1";

function domCacheKey(preset: SourcePreset | null): string {
  return preset?.name ? `preset:${preset.name}` : "__new__";
}

function readDomCache(): Record<string, { toc: DomSnapshot | null; chapter: DomSnapshot | null }> {
  try {
    const raw = sessionStorage.getItem(DOM_CACHE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, { toc: DomSnapshot | null; chapter: DomSnapshot | null }>) : {};
  } catch {
    return {};
  }
}

function writeDomCache(all: Record<string, { toc: DomSnapshot | null; chapter: DomSnapshot | null }>) {
  try {
    sessionStorage.setItem(DOM_CACHE_KEY, JSON.stringify(all));
  } catch {
    // quota exceeded - best effort, ignore
  }
}

function getDomForKey(key: string): { toc: DomSnapshot | null; chapter: DomSnapshot | null } | null {
  try {
    const all = readDomCache();
    return all[key] ?? null;
  } catch {
    return null;
  }
}

function setDomForKey(key: string, data: { toc: DomSnapshot | null; chapter: DomSnapshot | null }) {
  const all = readDomCache();
  all[key] = data;
  writeDomCache(all);
}

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
  { key: "url", label: "URL trang chủ / mục lục mẫu", kind: "text", wide: true, hint: "Dùng để gợi ý domain và test selector. Không lưu vào preset crawl." },
  { key: "domains", label: "Domain nhận diện (phẩy)", kind: "text", hint: "vd: 69shuba.com,69shu.com - ebook có URL chứa domain này sẽ tự gắn preset" },
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
  // chapter_link_pattern sẽ render riêng bằng RegexField có wrapper hint
];

// Các field selector/regex render riêng bằng SelectorField/RegexField (xem PresetModal)
// để có picker DOM + đếm khớp + cảnh báo, thay vì FieldGroup tĩnh.

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
  { key: "strip_patterns", label: "Regex loại bỏ nội dung thừa (1 dòng / pattern)", kind: "textarea", wide: true, hint: "Mỗi dòng 1 regex Python - loại bỏ dòng chứa quảng cáo/rác sau khi trích nội dung." },
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
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {fields.map((spec) => (
          <div key={spec.key} className={clsx(spec.wide && "md:col-span-2 lg:col-span-3")}>
            <FieldControl spec={spec} value={draft[spec.key]} onChange={(v) => onChange(spec.key, v)} />
          </div>
        ))}
      </div>
    </fieldset>
  );
}

function SubCard({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-200/30 p-3 space-y-3">
      <div className="text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</div>
      {hint ? <p className="text-[11px] leading-relaxed opacity-60">{hint}</p> : null}
      {children}
    </div>
  );
}

function PairCard({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-100 p-3 space-y-3">
      <div className="text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</div>
      {hint ? <p className="text-[11px] leading-relaxed opacity-60">{hint}</p> : null}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{children}</div>
    </div>
  );
}

const COVER_QUICK = [
  { label: "\\.webp$", value: "\\.webp$", title: "Ảnh webp" },
  { label: "jpe?g|png|webp", value: "\\.(?:jpe?g|png|webp)(?:[?\"']|$)", title: "Đuôi ảnh phổ biến" },
  { label: "…cover…", value: "cover[^\"'\\s]*", title: "URL chứa 'cover'" },
];

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
  // Tab form: toc (mục lục) | chapter (chương) | meta (ảnh bìa + crawl) | advanced
  const [tab, setTab] = useState<"toc" | "chapter" | "meta" | "advanced">("toc");

  // DOM lab - lưu trữ snapshot để picker/warning dùng chung (persist qua sessionStorage, ghi đè khi tải lại)
  const cacheKey = domCacheKey(preset);
  const [tocDom, setTocDom] = useState<DomSnapshot | null>(() => getDomForKey(cacheKey)?.toc ?? null);
  const [chapterDom, setChapterDom] = useState<DomSnapshot | null>(() => getDomForKey(cacheKey)?.chapter ?? null);
  const [validateLoading, setValidateLoading] = useState(false);
  const [validateWarnings, setValidateWarnings] = useState<string[]>([]);
  const [aiSuggestLoading, setAiSuggestLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setName(preset?.name ?? "");
      setDraft(preset ?? EMPTY_PRESET);
      const cached = getDomForKey(domCacheKey(preset));
      setTocDom(cached?.toc ?? null);
      setChapterDom(cached?.chapter ?? null);
      setValidateWarnings([]);
      setTab("toc");
    }
  }, [open, preset]);

  const set = (k: string, v: unknown) => setDraft((prev) => ({ ...prev, [k]: v }));

  const handleInspectDom = (info: { html: string; sampleLinks: string[]; url: string; which: "toc" | "chapter" }) => {
    const snap: DomSnapshot = { html: info.html, sampleLinks: info.sampleLinks, url: info.url };
    if (info.which === "toc") {
      const nextChapter = chapterDom;
      setTocDom(snap);
      setDomForKey(cacheKey, { toc: snap, chapter: nextChapter });
    } else {
      const nextToc = tocDom;
      setChapterDom(snap);
      setDomForKey(cacheKey, { toc: nextToc, chapter: snap });
    }
  };

  const runValidate = async () => {
    const hasToc = Boolean(tocDom?.html?.trim());
    const hasChap = Boolean(chapterDom?.html?.trim());
    if (!hasToc && !hasChap) { toast("Tải DOM Mục lục hoặc Chương mẫu trước đã.", "error"); return; }

    const pickSelectors = (keys: (keyof SourcePreset & string)[]) => {
      const out: Record<string, string> = {};
      for (const k of keys) {
        const v = String((draft as unknown as Record<string, unknown>)[k] || "").trim();
        if (v) out[k] = v;
      }
      return out;
    };

    type ValidateRes = { counts: Record<string, number>; pattern_hits: Record<string, { ok: boolean; matched: number; total: number; error?: string }>; warnings: string[] };
    const TOC_KEYS = ["toc_selector", "title_selector", "author_selector", "desc_selector", "cover_selector", "toc_next_page_selector"] as const;
    const CHAPTER_KEYS = ["content_selector", "chapter_title_selector", "next_page_selector"] as const;

    // cover_url_pattern: chỉ kiểm cú pháp regex phía client - sample links là
    // link chương nên endpoint không đối chiếu được. Lỗi cú pháp gom vào
    // allWarnings sau khi khai báo.
    const coverPat = String(draft.cover_url_pattern || "").trim();
    let coverPatternError = "";
    if (coverPat) {
      try {
        new RegExp(coverPat);
      } catch (e) {
        coverPatternError = `Ảnh bìa: cover_url_pattern lỗi cú pháp regex - ${e instanceof Error ? e.message : String(e)}`;
      }
    }

    setValidateLoading(true);
    try {
      const allWarnings: string[] = [];
      if (coverPatternError) allWarnings.push(coverPatternError);

      if (hasToc) {
        const selectors = pickSelectors([...TOC_KEYS] as unknown as (keyof SourcePreset & string)[]);
        const patterns: Record<string, string> = {};
        const chap = String(draft.chapter_link_pattern || "").trim();
        if (chap) patterns["chapter_link_pattern"] = chap;
        // chỉ kiểm TOC selectors trên DOM Mục lục
        if (Object.keys(selectors).length || Object.keys(patterns).length) {
          const res = await api.post<ValidateRes>("/api/ui/sources/validate-selectors", {
            body: { html: tocDom!.html, url: tocDom!.url || draft.url, selectors, patterns, sample_links: tocDom!.sampleLinks || [] },
          });
          allWarnings.push(...(res.warnings || []).map((w) => `Mục lục: ${w}`));
        }
      }

      if (hasChap) {
        const selectors = pickSelectors([...CHAPTER_KEYS] as unknown as (keyof SourcePreset & string)[]);
        const patterns: Record<string, string> = {};
        const nxt = String(draft.next_page_url_pattern || "").trim();
        if (nxt) patterns["next_page_url_pattern"] = nxt;
        if (Object.keys(selectors).length || Object.keys(patterns).length) {
          const res = await api.post<ValidateRes>("/api/ui/sources/validate-selectors", {
            body: { html: chapterDom!.html, url: chapterDom!.url || tocDom?.url || draft.url, selectors, patterns, sample_links: [] },
          });
          allWarnings.push(...(res.warnings || []).map((w) => `Chương: ${w}`));
        }
      }

      // không có selector/pattern nào để kiểm thì vẫn báo OK thay vì im lặng
      if (allWarnings.length === 0) {
        const hasAnySelector = [...TOC_KEYS, ...CHAPTER_KEYS].some((k) => String((draft as unknown as Record<string, unknown>)[k] || "").trim());
        const hasAnyPattern = Boolean(String(draft.chapter_link_pattern || "").trim() || String(draft.next_page_url_pattern || "").trim() || coverPat);
        if (!hasAnySelector && !hasAnyPattern) {
          toast("Chưa nhập selector/regex nào để kiểm tra.", "info");
          setValidateWarnings([]);
          return;
        }
      }

      setValidateWarnings(allWarnings);
      toast(allWarnings.length ? `Tìm thấy ${allWarnings.length} cảnh báo (đã tách theo DOM).` : "Tất cả selector/regex OK trên đúng DOM.", allWarnings.length ? "info" : "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally { setValidateLoading(false); }
  };

  const runAiSuggest = async () => {
    if (!tocDom?.html && !chapterDom?.html) { toast("Tải DOM trước đã - bấm 'Tải DOM' ở 2 tab Mục lục / Chương mẫu.", "error"); return; }
    setAiSuggestLoading(true);
    try {
      const res = await api.post<{
        ok: boolean;
        fields: Record<string, string>;
        diagnostics: Record<string, number>;
        pattern_ok: boolean;
        pattern_hits: number;
      }>("/api/ui/sources/suggest", {
        body: {
          html_toc: tocDom?.html || "",
          html_chapter: chapterDom?.html || tocDom?.html || "",
          toc_url: tocDom?.url || draft.url || "",
          chapter_url: chapterDom?.url || tocDom?.sampleLinks[0] || draft.url || "",
          sample_links: tocDom?.sampleLinks || [],
        },
      });
      let applied = 0;
      for (const [k, v] of Object.entries(res.fields || {})) {
        const trimmed = String(v || "").trim();
        if (trimmed) {
          (set as (k2: string, v2: unknown) => void)(k, trimmed);
          applied += 1;
        }
      }
      const dc = res.diagnostics || {};
      const zero = Object.entries(dc).filter(([, c]) => c === 0).map(([k]) => k);
      if (zero.length) toast(`AI đã điền ${applied} field - nhưng ${zero.join(", ")} đang "0 khớp" trên DOM đã tải. Nên kiểm tra lại và dùng "Chọn từ DOM".`, "info");
      else toast(`Đã điền ${applied} field từ AI gợi ý. Kiểm tra indicator màu bên dưới rồi bấm "Kiểm tra selector trên DOM".`, "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally { setAiSuggestLoading(false); }
  };

  const submit = () => {
    if (!name.trim()) {
      toast("Cần tên nguồn.", "error");
      return;
    }
    if (draft.chapter_link_pattern.trim() === ".*" || draft.chapter_link_pattern.trim() === ".+" ) {
      toast("Regex link chương đang là '.*' - sẽ khớp toàn bộ link trên trang. Hãy thu hẹp trước khi lưu.", "info");
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

  const tocHtml = tocDom?.html || "";
  const chapterHtml = chapterDom?.html || "";
  const tocSampleLinks = tocDom?.sampleLinks || [];
  const tocImageUrls = useMemo(() => extractImageUrls(tocHtml, tocDom?.url || ""), [tocHtml, tocDom?.url]);

  // tabs: toc (mục lục + ảnh bìa) | chapter (nội dung + phân trang) | advanced (crawl nâng cao)
  type TabKey = "toc" | "chapter" | "meta" | "advanced";
  const tabs: { key: TabKey; label: string }[] = [
    { key: "toc", label: "① Mục lục" },
    { key: "chapter", label: "② Chương" },
    { key: "meta", label: "Ảnh bìa & Crawl" },
    { key: "advanced", label: "Nâng cao" },
  ];
  const tabBadges: Record<TabKey, ReactNode> = {
    toc: tocHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{Math.round(tocHtml.length / 1024)} KB · {tocSampleLinks.length} link</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa tải</Badge>,
    chapter: chapterHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{Math.round(chapterHtml.length / 1024)} KB</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa tải</Badge>,
    meta: tocHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{tocImageUrls.length} ảnh</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa có DOM</Badge>,
    advanced: <Badge tone="indigo" className="normal-case text-[10px]">{CRAWL_FIELDS.length} field</Badge>,
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={preset ? `Sửa nguồn - ${preset.name}` : "Thêm nguồn"}
      xl
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
        {/* ── 0. Phòng thí nghiệm DOM - ghim lên đầu (dùng chung cho cả tabs) ── */}
        <div className="space-y-2">
          <DomInspector
            tocUrl={draft.url || ""}
            chapterUrl={tocSampleLinks[0] || draft.url || ""}
            scraplingMode={String(draft.scrapling_mode || "stealthy")}
            onDom={handleInspectDom}
            toc={tocDom}
            chapter={chapterDom}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" loading={aiSuggestLoading} onClick={runAiSuggest} disabled={!tocHtml && !chapterHtml}>✦ AI gợi ý selector</Button>
            <Button size="sm" loading={validateLoading} onClick={runValidate} disabled={!tocHtml && !chapterHtml}>Kiểm tra selector trên DOM</Button>
            {tocDom || chapterDom ? (
              <span className="text-xs opacity-60">TOC {tocDom ? `${Math.round(tocDom.html.length / 1024)} KB` : "-"} · Chương {chapterDom ? `${Math.round(chapterDom.html.length / 1024)} KB` : "-"} · tải lại sẽ ghi đè</span>
            ) : (
              <span className="text-xs opacity-50">Tải cả 2 loại DOM để selector đếm khớp chính xác nhất.</span>
            )}
          </div>
          {validateWarnings.length > 0 ? (
            <ul className="list-disc pl-5 text-xs space-y-1 rounded-box border border-base-300 bg-base-200/50 p-2 pr-3">
              {validateWarnings.map((w, i) => (
                <li key={i} className={clsx(w.includes("quá rộng") || w.includes("toàn bộ") ? "text-warning" : w.includes("lỗi") || w.includes("không khớp") ? "text-error" : "opacity-80")}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>

        <Field label="Tên nguồn" hint="Định danh duy nhất, ebook tham chiếu bằng tên này">
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={Boolean(preset)} className="w-full" />
        </Field>

        {/* ── Tab bar (tabs-box - dùng mẫu GlossaryPage/AddBookPage) ── */}
        <div role="tablist" className="tabs tabs-box Tabs tabs-sm w-fit">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              type="button"
              className={clsx("tab gap-1.5 whitespace-nowrap", tab === t.key && "tab-active")}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              <span className="hidden sm:inline">{tabBadges[t.key]}</span>
            </button>
          ))}
        </div>

        {/* ── Tab ① Mục lục ── */}
        {tab === "toc" ? (
          <div className="grid gap-3">
            <p className="text-[11px] leading-relaxed opacity-60">Các field bên dưới chỉ đếm khớp trên <b>DOM Mục lục</b> đã tải ở phòng lab trên. “Chọn từ DOM” sẽ mở đúng HTML Mục lục. {!tocHtml ? <span className="text-warning">Tải DOM Mục lục để bật đếm khớp &amp; gợi ý.</span> : null}</p>
            {/* Wrapper + Regex phối hợp - nhóm chính */}
            <PairCard
              title="Link chương - wrapper + regex phối hợp"
              hint="Crawler chỉ xét các <a> nằm trong Wrapper mục lục, rồi mới lọc bằng Regex. Thu hẹp wrapper (vd #list) + regex cụ thể (vd /chuong-\d+\.html$) loại menu/nav."
            >
              <SelectorField
                label="Wrapper mục lục"
                hint="Container chứa danh sách chương"
                value={String(draft.toc_selector || "")}
                onChange={(v) => set("toc_selector", v)}
                html={tocHtml}
                placeholder="#list, .chapter-list, #tbchapterlist"
                wrapperNote="wrapper · DOM Mục lục"
                candidateKind="link-wrapper"
              />
              <RegexField
                label="Regex lọc link chương"
                hint="Chỉ khớp URL CHƯƠNG tuyệt đối. Tránh '.*' - lấy cả menu/nav. VD: /chuong-\\d+\\.html$"
                value={String(draft.chapter_link_pattern || "")}
                onChange={(v) => set("chapter_link_pattern", v)}
                sampleLinks={tocSampleLinks}
                placeholder="vd: /chuong-\\d+\\.html$"
              />
            </PairCard>

            <SubCard title="Metadata truyện - DOM Mục lục" hint="Thông tin trích từ trang mục lục (tiêu đề, tác giả, mô tả).">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                <SelectorField label="Wrapper tên truyện" hint="Ở trang mục lục" value={String(draft.title_selector || "")} onChange={(v) => set("title_selector", v)} html={tocHtml} placeholder="h1, .book-title" expectOne candidateKind="heading" />
                <SelectorField label="Wrapper tác giả" hint="DOM Mục lục" value={String(draft.author_selector || "")} onChange={(v) => set("author_selector", v)} html={tocHtml} placeholder=".author, #author" expectOne candidateKind="keyword" candidateKeywords={["author", "zuozhe", "tac-gia", "tacgia"]} />
                <SelectorField label="Wrapper mô tả" hint="DOM Mục lục" value={String(draft.desc_selector || "")} onChange={(v) => set("desc_selector", v)} html={tocHtml} placeholder="#intro, .desc" expectOne candidateKind="keyword" candidateKeywords={["desc", "intro", "summary", "gioi-thieu", "gioithieu"]} />
              </div>
            </SubCard>

            <PairCard
              title="Phân trang mục lục - wrapper trang kế + số trang"
              hint="Link 'Trang kế' ở mục lục; để trống = chỉ 1 trang."
            >
              <SelectorField
                label="Wrapper trang kế (mục lục)"
                hint="DOM Mục lục"
                value={String(draft.toc_next_page_selector || "")}
                onChange={(v) => set("toc_next_page_selector", v)}
                html={tocHtml}
                placeholder=".pagination a.next, a#next"
                expectOne
                candidateKind="next-link"
              />
              <Field label="Số trang mục lục tối đa" hint="1 = chỉ trang đầu">
                <Input type="number" value={String(draft.toc_max_pages ?? 5)} onChange={(e) => set("toc_max_pages", e.target.value === "" ? 5 : Number(e.target.value))} />
              </Field>
            </PairCard>
          </div>
        ) : null}

        {/* ── Tab ② Chương ── */}
        {tab === "chapter" ? (
          <div className="grid gap-3">
            <p className="text-[11px] leading-relaxed opacity-60">Các field bên dưới chỉ đếm khớp trên <b>DOM Chương mẫu</b>. “Chọn từ DOM” sẽ mở đúng HTML chương. {!chapterHtml ? <span className="text-warning">Tải DOM Chương mẫu để bật đếm khớp &amp; gợi ý.</span> : null}</p>
            <SubCard
              title="Nội dung chương - wrapper chính"
              hint="Container hẹp nhất bao trọn phần chữ - fallback #content nếu trống. DOM Chương mẫu."
            >
              <SelectorField
                label="Wrapper nội dung chương"
                hint="Container nội dung thực của trang chương"
                value={String(draft.content_selector || "")}
                onChange={(v) => set("content_selector", v)}
                html={chapterHtml}
                placeholder="#content, #chaptercontent, .read-content"
                expectOne
                wrapperNote="wrapper · DOM Chương"
                candidateKind="text-wrapper"
              />
            </SubCard>

            <SelectorField label="Wrapper tiêu đề chương" hint="Ở TRANG CHƯƠNG · DOM Chương mẫu" value={String(draft.chapter_title_selector || "")} onChange={(v) => set("chapter_title_selector", v)} html={chapterHtml} placeholder="h1, .bookname h1" expectOne candidateKind="heading" />

            <PairCard
              title="Phân trang chương - wrapper + regex phối hợp"
              hint="Ưu tiên tìm link trang kế qua wrapper selector; regex là fallback khi chỉ có URL tăng số (nhóm bắt \\d+). Giới hạn số trang / chương tránh vòng lặp."
            >
              <SelectorField label="Wrapper trang kế (nội dung)" hint="DOM Chương mẫu" value={String(draft.next_page_selector || "")} onChange={(v) => set("next_page_selector", v)} html={chapterHtml} placeholder="a.next, #next_url" expectOne candidateKind="next-link" />
              <div className="space-y-3">
                <RegexField label="Regex URL trang kế" hint="Phải có 1 nhóm bắt (\\d+)" value={String(draft.next_page_url_pattern || "")} onChange={(v) => set("next_page_url_pattern", v)} sampleLinks={[]} placeholder="(\\d+)\\.html$" allowEmpty />
                <Field label="Số trang tối đa / chương" hint="Giới hạn phân trang chương">
                  <Input type="number" value={String(draft.max_pages_per_chapter ?? 10)} onChange={(e) => set("max_pages_per_chapter", e.target.value === "" ? 10 : Number(e.target.value))} />
                </Field>
              </div>
            </PairCard>
          </div>
        ) : null}

        {/* ── Tab Ảnh bìa & Crawl ── */}
        {tab === "meta" ? (
          <div className="grid gap-3">
            <p className="text-[11px] leading-relaxed opacity-60">Ảnh bìa lấy từ <b>DOM Mục lục</b>. og:image là nguồn mặc định; regex bên dưới là fallback khi og:image thiếu/sai (quét <code className="px-1 py-0.5 rounded bg-base-200">&lt;img&gt;</code> trong DOM mục lục).</p>

            <PairCard
              title="Ảnh bìa - wrapper + regex URL ảnh phối hợp"
              hint="og:image (meta chuẩn) → cover_selector → cover_url_pattern. Regex quét URL ảnh tuyệt đối từ DOM Mục lục; URL đầu tiên khớp được dùng nếu og:image thiếu. Đếm khớp dưới regex dựa trên URL ảnh đã trích từ DOM."
            >
              <SelectorField label="Wrapper ảnh bìa" hint="DOM Mục lục" value={String(draft.cover_selector || "")} onChange={(v) => set("cover_selector", v)} html={tocHtml} placeholder=".book-img img" expectOne candidateKind="image" />
              <RegexField
                label="Regex URL ảnh bìa"
                hint="Quét URL ảnh trong DOM mục lục; URL đầu khớp làm ảnh bìa khi og:image thiếu. VD: https://cdn\\.example\\.com/covers/.*\\.jpg"
                value={String(draft.cover_url_pattern || "")}
                onChange={(v) => set("cover_url_pattern", v)}
                sampleLinks={tocImageUrls}
                placeholder="vd: https://cdn\\.example\\.com/covers/.*\\.jpg"
                quick={COVER_QUICK}
                allowEmpty
              />
            </PairCard>

            <FieldGroup title="Cơ bản" fields={BASIC_FIELDS} draft={draft} onChange={set} />
          </div>
        ) : null}

        {/* ── Tab Nâng cao ── */}
        {tab === "advanced" ? (
          <FieldGroup title="Crawl nâng cao" fields={CRAWL_FIELDS} draft={draft} onChange={set} />
        ) : null}
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
      title={`Test nguồn - ${name}`}
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
                    toast("Đang test - kết quả hiện lại ở thẻ nguồn sau vài giây.");
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
  const isWildcard = preset.chapter_link_pattern.trim() === ".*" || preset.chapter_link_pattern.trim() === ".+";
  const hasTightWrapper = Boolean(preset.toc_selector && preset.toc_selector.trim());

  return (
    <Panel className="p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[15px] font-semibold">{preset.name}</h3>
          <p className="truncate text-xs opacity-60">{preset.domains || preset.url || "-"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {isWildcard ? (
            <Badge tone="vermilion" className="cursor-help">
              <span title="Regex '.*' khớp toàn bộ link - hãy thu hẹp">regex rộng</span>
            </Badge>
          ) : null}
          {!hasTightWrapper && preset.chapter_link_pattern ? (
            <Badge tone="gold" className="cursor-help">
              <span title="Thiếu wrapper mục lục - regex sẽ quét toàn trang">thiếu wrapper</span>
            </Badge>
          ) : null}
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
      hint="Preset crawl dùng lại cho nhiều truyện - selector wrapper, regex lọc link, chế độ crawl, delay, proxy"
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
