import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import {
  useEbookSettings,
  useGlobalAi,
  useSaveSettings,
  useEbookModelOverrides,
  useSaveEbookModelOverrides,
  type AiSettings,
  type EbookSettings,
  type OpdsSettings,
  type SettingsSection,
} from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { fetchAndMergeModels, ModelField } from "@/components/AiProviderFields";
import { DomInspector, RegexField, SelectorField, extractImageUrls } from "@/components/CrawlSelectorLab";

/* ── Mô tả field dùng chung cho mọi tab ──────────────────────────────── */

type Kind = "text" | "password" | "textarea" | "number" | "checkbox" | "select" | "model" | "base_url";

interface FieldSpec<T> {
  key: keyof T & string;
  label: string;
  kind: Kind;
  hint?: string;
  options?: { value: string; label: string }[];
  wide?: boolean;
  step?: number;
  disabledWhen?: (values: Record<string, unknown>) => boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function FieldControl({
  spec,
  value,
  values,
  onChange,
}: {
  spec: FieldSpec<any>;
  value: unknown;
  values: Record<string, unknown>;
  onChange: (next: unknown) => void;
}) {
  const disabled = spec.disabledWhen ? spec.disabledWhen(values) : false;
  const disabledNote = disabled ? (
    <span className="text-xs opacity-50">— không áp dụng ở chế độ hiện tại</span>
  ) : null;
  switch (spec.kind) {
    case "checkbox":
      return (
        <label className={clsx("flex items-center gap-2 py-1 text-[13px]", disabled && "opacity-50")}>
          <Checkbox checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          {spec.label}
          {spec.hint ? <span className="text-xs opacity-50">— {spec.hint}</span> : null}
          {disabled ? disabledNote : null}
        </label>
      );
    case "select":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Select value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
            {(spec.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
      );
    case "textarea":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Textarea
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            rows={spec.wide ? 8 : 3}
            spellCheck={false}
          />
        </Field>
      );
    case "number":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="number"
            step={spec.step ?? 1}
            value={String(value ?? 0)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
          />
        </Field>
      );
    case "password":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="password"
            autoComplete="off"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          />
        </Field>
      );
    case "model":
      return (
        <ModelField
          label={spec.label}
          hint={spec.hint}
          value={String(value ?? "")}
          baseUrl={String(values.base_url ?? "")}
          disabled={disabled}
          onChange={onChange}
        />
      );
    case "base_url":
      return (
        <BaseUrlField
          label={spec.label}
          hint={spec.hint}
          value={String(value ?? "")}
          apiKey={String(values.api_key ?? "")}
          disabled={disabled}
          onChange={onChange}
        />
      );
    default:
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
          />
        </Field>
      );
  }
}

function BaseUrlField({
  label,
  hint,
  value,
  apiKey,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  apiKey: string;
  disabled?: boolean;
  onChange: (next: unknown) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");

  const load = async () => {
    setLoading(true);
    setStatus("Đang tải...");
    const r = await fetchAndMergeModels(value, apiKey);
    setStatus(r.error ?? `Đã tải ${r.count} model (cache ${r.total}).`);
    setLoading(false);
  };

  return (
    <Field label={label} hint={hint}>
      <div className="join w-full">
        <Input
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="join-item flex-1 min-w-0"
        />
        <Button
          size="sm"
          loading={loading}
          disabled={disabled}
          onClick={load}
          className="join-item shrink-0"
          title="Lấy danh sách model từ {base_url}/models và tự lưu cache theo url"
        >
          Tải models
        </Button>
      </div>
      {status ? <span className="block text-xs italic opacity-60">{status}</span> : null}
    </Field>
  );
}

function SectionForm<S extends SettingsSection>({
  slug,
  section,
  title,
  hint,
  fields,
  server,
  banner,
  extraActions,
  renderExtraActions,
}: {
  slug: string;
  section: S;
  title: string;
  hint?: string;
  fields: FieldSpec<EbookSettings[S]>[];
  server: EbookSettings[S];
  banner?: React.ReactNode;
  extraActions?: React.ReactNode;
  renderExtraActions?: (draft: EbookSettings[S], setDraft: React.Dispatch<React.SetStateAction<EbookSettings[S]>>) => React.ReactNode;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState<EbookSettings[S]>(server);
  const save = useSaveSettings(slug, section);
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(server), [draft, server]);
  useEffect(() => {
    if (!dirty) setDraft(server);
  }, [server, dirty]);
  const set = (key: string, value: unknown) =>
    setDraft((prev) => ({ ...prev, [key]: value }));
  const onSave = () => {
    save.mutate(draft, {
      onSuccess: () => toast(`Đã lưu ${title.toLowerCase()}.`),
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };
  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title={title}
        hint={hint}
        actions={
          <>
            {extraActions}
            {renderExtraActions?.(draft, setDraft)}
            {dirty ? (
              <Button size="sm" onClick={() => setDraft(server)}>
                Hủy thay đổi
              </Button>
            ) : null}
            <Button size="sm" variant="primary" loading={save.isPending} disabled={!dirty} onClick={onSave}>
              Lưu
            </Button>
          </>
        }
      />
      {banner}
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 p-4 md:grid-cols-2 lg:grid-cols-3">
        {fields.map((spec) => (
          <div key={spec.key} className={clsx(spec.wide && "md:col-span-2 lg:col-span-3")}>
            <FieldControl
              spec={spec}
              value={draft[spec.key]}
              values={draft as unknown as Record<string, unknown>}
              onChange={(v) => set(spec.key, v)}
            />
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ── Helpers cho tab Nguồn — giống SourcesPage ─────────────────────── */

const SETTINGS_DOM_CACHE_KEY = "n2e:domLab:settings:v1";

function settingsDomCacheKey(slug: string): string {
  return `settings:${slug}`;
}

function readSettingsDomCache(): Record<string, { toc: { html: string; sampleLinks: string[]; url: string } | null; chapter: { html: string; sampleLinks: string[]; url: string } | null }> {
  try {
    const raw = sessionStorage.getItem(SETTINGS_DOM_CACHE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, { toc: { html: string; sampleLinks: string[]; url: string } | null; chapter: { html: string; sampleLinks: string[]; url: string } | null }>) : {};
  } catch {
    return {};
  }
}

function writeSettingsDomCache(all: Record<string, { toc: { html: string; sampleLinks: string[]; url: string } | null; chapter: { html: string; sampleLinks: string[]; url: string } | null }>) {
  try {
    sessionStorage.setItem(SETTINGS_DOM_CACHE_KEY, JSON.stringify(all));
  } catch {
    // quota exceeded — best effort
  }
}

function getSettingsDomForKey(slug: string): { toc: { html: string; sampleLinks: string[]; url: string } | null; chapter: { html: string; sampleLinks: string[]; url: string } | null } | null {
  try {
    const all = readSettingsDomCache();
    return all[settingsDomCacheKey(slug)] ?? null;
  } catch {
    return null;
  }
}

function setSettingsDomForKey(slug: string, data: { toc: { html: string; sampleLinks: string[]; url: string } | null; chapter: { html: string; sampleLinks: string[]; url: string } | null }) {
  const all = readSettingsDomCache();
  all[settingsDomCacheKey(slug)] = data;
  writeSettingsDomCache(all);
}

const SETTINGS_COVER_QUICK = [
  { label: "\\.webp$", value: "\\.webp$", title: "Ảnh webp" },
  { label: "jpe?g|png|webp", value: "\\.(?:jpe?g|png|webp)(?:[?\"']|$)", title: "Đuôi ảnh phổ biến" },
  { label: "…cover…", value: "cover[^\"'\\s]*", title: "URL chứa 'cover'" },
];

function SettingsSubCard({ title, hint, children }: { title: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-200/30 p-3 space-y-3">
      <div className="text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</div>
      {hint ? <p className="text-[11px] leading-relaxed opacity-60">{hint}</p> : null}
      {children}
    </div>
  );
}

function SettingsPairCard({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-100 p-3 space-y-3">
      <div className="text-[11px] font-semibold tracking-wide uppercase opacity-60">{title}</div>
      {hint ? <p className="text-[11px] leading-relaxed opacity-60">{hint}</p> : null}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{children}</div>
    </div>
  );
}

/* ── Enhanced Source tab với DOM lab ──────────────────────────────── */

function SourceTab({ slug, server, banner }: { slug: string; server: EbookSettings["source"]; banner?: React.ReactNode }) {
  const toast = useToast();
  const [draft, setDraft] = useState<EbookSettings["source"]>(server);
  const save = useSaveSettings(slug, "source");
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(server), [draft, server]);
  useEffect(() => { if (!dirty) setDraft(server); }, [server, dirty]);

  const [tocDom, setTocDom] = useState<{ html: string; sampleLinks: string[]; url: string } | null>(() => getSettingsDomForKey(slug)?.toc ?? null);
  const [chapterDom, setChapterDom] = useState<{ html: string; sampleLinks: string[]; url: string } | null>(() => getSettingsDomForKey(slug)?.chapter ?? null);
  const [tab, setTab] = useState<"toc" | "chapter" | "meta" | "advanced">("toc");
  const [validateLoading, setValidateLoading] = useState(false);
  const [validateWarnings, setValidateWarnings] = useState<string[]>([]);

  const tocHtml = tocDom?.html || "";
  const chapterHtml = chapterDom?.html || "";
  const tocSampleLinks = tocDom?.sampleLinks || [];
  const tocImageUrls = useMemo(() => extractImageUrls(tocHtml, tocDom?.url || ""), [tocHtml, tocDom?.url]);

  const set = (key: string, value: unknown) => setDraft((prev) => ({ ...prev, [key]: value as never }));

  const onSave = () => {
    if (String(draft.chapter_link_pattern || "").trim() === ".*") {
      toast("Regex link chương đang là '.*' — sẽ khớp toàn bộ link. Hãy thu hẹp trước khi lưu.", "info");
    }
    save.mutate(draft, {
      onSuccess: () => toast("Đã lưu nguồn."),
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };

  const handleDom = (info: { html: string; sampleLinks: string[]; url: string; which: "toc" | "chapter" }) => {
    const snap = { html: info.html, sampleLinks: info.sampleLinks, url: info.url };
    if (info.which === "toc") {
      const nextChapter = chapterDom;
      setTocDom(snap);
      setSettingsDomForKey(slug, { toc: snap, chapter: nextChapter });
    } else {
      const nextToc = tocDom;
      setChapterDom(snap);
      setSettingsDomForKey(slug, { toc: nextToc, chapter: snap });
    }
  };

  const runValidate = async () => {
    const hasToc = Boolean(tocDom?.html?.trim());
    const hasChap = Boolean(chapterDom?.html?.trim());
    if (!hasToc && !hasChap) { toast("Tải DOM mục lục/chương trước đã.", "error"); return; }
    const pickSelectors = (keys: (keyof EbookSettings["source"] & string)[]) => {
      const out: Record<string, string> = {};
      for (const k of keys) {
        const v = String((draft as unknown as Record<string, unknown>)[k] || "").trim();
        if (v) out[k] = v;
      }
      return out;
    };
    type ValidateRes = { counts: Record<string, number>; pattern_hits: Record<string, { ok: boolean; matched: number; total: number; error?: string }>; warnings: string[] };
    const TOC_KEYS = ["toc_next_page_selector"] as const;
    const CHAPTER_KEYS = ["content_selector", "next_page_selector"] as const;
    const coverPat = String((draft as unknown as Record<string, unknown>).cover_url_pattern || "").trim();
    let coverPatternError = "";
    if (coverPat) {
      try { new RegExp(coverPat); } catch (e) { coverPatternError = `Ảnh bìa: cover_url_pattern lỗi cú pháp — ${e instanceof Error ? e.message : String(e)}`; }
    }
    setValidateLoading(true);
    try {
      const allWarnings: string[] = [];
      if (coverPatternError) allWarnings.push(coverPatternError);
      if (hasToc) {
        const selectors = pickSelectors([...TOC_KEYS] as unknown as (keyof EbookSettings["source"] & string)[]);
        const patterns: Record<string, string> = {};
        const chap = String(draft.chapter_link_pattern || "").trim();
        if (chap) patterns["chapter_link_pattern"] = chap;
        if (Object.keys(selectors).length || Object.keys(patterns).length) {
          const res = await api.post<ValidateRes>("/api/ui/sources/validate-selectors", { body: { html: tocDom!.html, url: tocDom!.url || draft.toc_url, selectors, patterns, sample_links: tocDom!.sampleLinks || [] } });
          allWarnings.push(...(res.warnings || []).map((w) => `Mục lục: ${w}`));
        }
      }
      if (hasChap) {
        const selectors = pickSelectors([...CHAPTER_KEYS] as unknown as (keyof EbookSettings["source"] & string)[]);
        const patterns: Record<string, string> = {};
        const nxt = String(draft.next_page_url_pattern || "").trim();
        if (nxt) patterns["next_page_url_pattern"] = nxt;
        if (Object.keys(selectors).length || Object.keys(patterns).length) {
          const res = await api.post<ValidateRes>("/api/ui/sources/validate-selectors", { body: { html: chapterDom!.html, url: chapterDom!.url || tocDom?.url || draft.toc_url, selectors, patterns, sample_links: [] } });
          allWarnings.push(...(res.warnings || []).map((w) => `Chương: ${w}`));
        }
      }
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
      toast(allWarnings.length ? `Có ${allWarnings.length} cảnh báo (đã tách theo DOM).` : "Selector/regex OK trên đúng DOM.", allWarnings.length ? "info" : "ok");
    } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); }
    finally { setValidateLoading(false); }
  };

  const tabs: { key: "toc" | "chapter" | "meta" | "advanced"; label: string }[] = [
    { key: "toc", label: "① Mục lục" },
    { key: "chapter", label: "② Chương" },
    { key: "meta", label: "Ảnh bìa & Crawl" },
    { key: "advanced", label: "Nâng cao" },
  ];
  const tabBadges: Record<"toc" | "chapter" | "meta" | "advanced", React.ReactNode> = {
    toc: tocHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{Math.round(tocHtml.length / 1024)} KB · {tocSampleLinks.length} link</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa tải</Badge>,
    chapter: chapterHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{Math.round(chapterHtml.length / 1024)} KB</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa tải</Badge>,
    meta: tocHtml ? <Badge tone="celadon" className="normal-case text-[10px]">{tocImageUrls.length} ảnh</Badge> : <Badge tone="gold" className="normal-case text-[10px]">chưa có DOM</Badge>,
    advanced: <Badge tone="indigo" className="normal-case text-[10px]">nâng cao</Badge>,
  };

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Nguồn"
        hint="Cách crawl mục lục và nội dung chương — wrapper thu hẹp phạm vi, regex lọc link; DOM riêng từng truyện được lưu qua sessionStorage"
        actions={
          <>
            {dirty ? <Button size="sm" onClick={() => setDraft(server)}>Hủy thay đổi</Button> : null}
            <Button size="sm" variant="primary" loading={save.isPending} disabled={!dirty} onClick={onSave}>Lưu</Button>
          </>
        }
      />
      {banner}
      <div className="p-4 space-y-4">
        {/* URL mục lục — luôn hiện vì là nguồn của DOM lab */}
        <Field label="URL mục lục" hint="Dán link trang danh sách chương để test selector/regex bên dưới">
          <Input value={String(draft.toc_url || "")} onChange={(e) => set("toc_url", e.target.value)} placeholder="https://example.com/book/123/" spellCheck={false} className="w-full font-mono text-xs" />
        </Field>

        {/* DOM lab — lưu riêng TOC + Chương mẫu cho truyện này, ghi đè khi tải lại */}
        <div className="space-y-2 rounded-box border border-base-300 bg-base-100 p-3">
          <DomInspector tocUrl={String(draft.toc_url || "")} chapterUrl={tocSampleLinks[0] || ""} scraplingMode={String(draft.scrapling_mode || "fetcher")} onDom={handleDom} toc={tocDom} chapter={chapterDom} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" loading={validateLoading} onClick={runValidate} disabled={!tocHtml && !chapterHtml}>Kiểm tra wrapper/regex trên DOM</Button>
            {tocDom || chapterDom ? <span className="text-xs opacity-50 self-center">TOC {tocDom ? `${Math.round(tocDom.html.length / 1024)} KB` : "—"} · Chương {chapterDom ? `${Math.round(chapterDom.html.length / 1024)} KB` : "—"} · tải lại sẽ ghi đè</span> : <span className="text-xs opacity-50 self-center">Tải cả 2 loại DOM để kiểm chính xác — DOM lưu riêng theo truyện, qua sessionStorage.</span>}
          </div>
          {validateWarnings.length > 0 ? (
            <ul className="list-disc pl-5 text-xs space-y-1">
              {validateWarnings.map((w, i) => <li key={i} className={clsx(w.includes("quá rộng") || w.includes("toàn bộ") ? "text-warning" : w.includes("lỗi") || w.includes("không khớp") ? "text-error" : "opacity-80")}>{w}</li>)}
            </ul>
          ) : null}
        </div>

        {/* Tabs: Toc | Chapter | Meta | Advanced */}
        <div role="tablist" className="tabs tabs-box tabs-sm w-fit">
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

        {tab === "toc" ? (
          <div className="space-y-3">
            <p className="text-[11px] leading-relaxed opacity-60">Các field bên dưới chỉ đếm khớp trên <b>DOM Mục lục</b> đã tải ở phòng lab trên. “Chọn từ DOM” sẽ mở đúng HTML Mục lục. {!tocHtml ? <span className="text-warning">Tải DOM Mục lục để bật đếm khớp &amp; gợi ý.</span> : null}</p>
            <SettingsPairCard
              title="Link chương — wrapper + regex phối hợp"
              hint="Crawler chỉ xét các <a> nằm trong Wrapper mục lục, rồi mới lọc bằng Regex. Thu hẹp wrapper (vd #list) + regex cụ thể (vd /chuong-\\d+\\.html$) loại menu/nav."
            >
              <div className="space-y-1 text-[11px] opacity-60">Wrapper mục lục sẽ dùng preset/mặc định nếu để trống ở đây. Chỉ ghi đè khi muốn test riêng truyện này.</div>
              <RegexField
                label="Regex lọc link chương"
                hint="Chỉ khớp URL CHƯƠNG tuyệt đối. Tránh '.*' — sẽ lấy cả menu/nav/footer → crawl hàng trăm URL rác. VD: /chuong-\\d+\\.html$ hoặc /book/\\d+/\\d+\\.html$"
                value={String(draft.chapter_link_pattern || "")}
                onChange={(v) => set("chapter_link_pattern", v)}
                sampleLinks={tocSampleLinks}
                placeholder="vd: /chuong-\\d+\\.html$"
              />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <SelectorField label="Wrapper trang kế (mục lục)" hint="Link 'Trang kế' ở mục lục — để trống = chỉ 1 trang." value={String(draft.toc_next_page_selector || "")} onChange={(v) => set("toc_next_page_selector", v)} html={tocHtml} placeholder=".pagination a.next" expectOne candidateKind="next-link" />
                <Field label="Số trang mục lục tối đa" hint="1 = chỉ trang đầu"><Input type="number" value={String((draft as unknown as { toc_max_pages: number }).toc_max_pages ?? 5)} onChange={(e) => set("toc_max_pages", e.target.value === "" ? 5 : Number(e.target.value))} /></Field>
              </div>
            </SettingsPairCard>
          </div>
        ) : null}

        {tab === "chapter" ? (
          <div className="space-y-3">
            <p className="text-[11px] leading-relaxed opacity-60">Các field bên dưới chỉ đếm khớp trên <b>DOM Chương mẫu</b>. “Chọn từ DOM” sẽ mở đúng HTML chương. {!chapterHtml ? <span className="text-warning">Tải DOM Chương mẫu để bật đếm khớp &amp; gợi ý.</span> : null}</p>
            <SettingsSubCard title="Wrapper nội dung chương" hint="Container hẹp nhất bao trọn phần chữ — fallback #content nếu trống. DOM Chương mẫu.">
              <SelectorField label="Wrapper nội dung chương" hint="Container nội dung thực của trang chương" value={String(draft.content_selector || "")} onChange={(v) => set("content_selector", v)} html={chapterHtml || tocHtml} placeholder="#content, #chaptercontent, .read-content" expectOne wrapperNote="wrapper" candidateKind="text-wrapper" />
            </SettingsSubCard>
            <SettingsPairCard
              title="Phân trang chương — wrapper + regex phối hợp"
              hint="Ưu tiên tìm link trang kế qua wrapper selector; regex là fallback khi chỉ có URL tăng số (nhóm bắt \\d+). Giới hạn số trang / chương tránh vòng lặp."
            >
              <SelectorField label="Wrapper trang kế (nội dung)" hint="DOM Chương mẫu" value={String(draft.next_page_selector || "")} onChange={(v) => set("next_page_selector", v)} html={chapterHtml || tocHtml} placeholder="a.next, #next_url" expectOne candidateKind="next-link" />
              <div className="space-y-3">
                <RegexField label="Regex URL trang kế" hint="Phải có 1 nhóm bắt (\\d+)" value={String(draft.next_page_url_pattern || "")} onChange={(v) => set("next_page_url_pattern", v)} sampleLinks={[]} placeholder="(\\d+)\\.html$" allowEmpty />
                <Field label="Số trang tối đa / chương"><Input type="number" value={String(draft.max_pages_per_chapter ?? 10)} onChange={(e) => set("max_pages_per_chapter", e.target.value === "" ? 10 : Number(e.target.value))} /></Field>
              </div>
            </SettingsPairCard>
            <Field label="Giới hạn số chương" hint="0 = không giới hạn"><Input type="number" value={String(draft.max_chapters ?? 0)} onChange={(e) => set("max_chapters", e.target.value === "" ? 0 : Number(e.target.value))} /></Field>
          </div>
        ) : null}

        {tab === "meta" ? (
          <div className="space-y-3">
            <p className="text-[11px] leading-relaxed opacity-60">Ảnh bìa lấy từ <b>DOM Mục lục</b>. og:image là mặc định; regex bên dưới là fallback khi og:image thiếu/sai (quét <code className="px-1 py-0.5 rounded bg-base-200">&lt;img&gt;</code> trong DOM mục lục, URL đầu khớp được dùng).</p>
            <SettingsPairCard
              title="Ảnh bìa — regex URL ảnh (fallback og:image)"
              hint="Regex quét URL ảnh tuyệt đối từ DOM Mục lục; URL đầu tiên khớp được dùng nếu og:image thiếu. Đếm khớp dưới regex dựa trên URL ảnh đã trích từ DOM."
            >
              <RegexField
                label="Regex URL ảnh bìa"
                hint="Quét URL ảnh trong DOM mục lục; URL đầu khớp làm ảnh bìa khi og:image thiếu. VD: https://cdn\\.example\\.com/covers/.*\\.jpg"
                value={String((draft as unknown as Record<string, unknown>).cover_url_pattern || "")}
                onChange={(v) => set("cover_url_pattern", v)}
                sampleLinks={tocImageUrls}
                placeholder="vd: https://cdn\\.example\\.com/covers/.*\\.jpg"
                quick={SETTINGS_COVER_QUICK}
                allowEmpty
              />
            </SettingsPairCard>
            <p className="text-[11px] opacity-60">Các field crawl cơ bản (delay, proxy, retry…) nằm ở tab <b>Nâng cao</b>. Override ở đây chỉ ghi đè preset/mặc định khi cần test riêng truyện này.</p>
          </div>
        ) : null}

        {tab === "advanced" ? (
          <fieldset className="rounded-box border border-base-300 p-3">
            <legend className="px-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">Crawl nâng cao — ghi đè riêng truyện này</legend>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              <Field label="Delay giữa các request (giây)"><Input type="number" step={0.1} value={String(draft.delay_seconds ?? 1)} onChange={(e) => set("delay_seconds", e.target.value === "" ? 1 : Number(e.target.value))} /></Field>
              <Field label="Số luồng crawl song song"><Input type="number" value={String(draft.max_workers ?? 1)} onChange={(e) => set("max_workers", e.target.value === "" ? 1 : Number(e.target.value))} /></Field>
              <Field label="Trần song song theo nguồn" hint="0 = mặc định theo chế độ crawl"><Input type="number" value={String(draft.concurrency_cap ?? 0)} onChange={(e) => set("concurrency_cap", e.target.value === "" ? 0 : Number(e.target.value))} /></Field>
              <Field label="Impersonate (fingerprint trình duyệt)"><Input value={String(draft.impersonate || "")} onChange={(e) => set("impersonate", e.target.value)} spellCheck={false} /></Field>
              <Field label="Proxy"><Input value={String(draft.proxy || "")} onChange={(e) => set("proxy", e.target.value)} placeholder="http://... hoặc socks5://host:port" spellCheck={false} /></Field>
              <Field label="Chế độ crawl">
                <Select value={String(draft.scrapling_mode || "fetcher")} onChange={(e) => set("scrapling_mode", e.target.value)}>
                  <option value="fetcher">fetcher (nhanh nhất)</option>
                  <option value="stealthy">stealthy</option>
                  <option value="dynamic">dynamic (render JS)</option>
                </Select>
              </Field>
              <label className="flex items-center gap-2 py-1 text-[13px]"><Checkbox checked={Boolean(draft.headless)} disabled={draft.scrapling_mode === "fetcher"} onChange={(e) => set("headless", e.target.checked)} />Chạy headless {draft.scrapling_mode === "fetcher" ? <span className="text-xs opacity-50">— không áp dụng ở fetcher</span> : null}</label>
              <label className="flex items-center gap-2 py-1 text-[13px]"><Checkbox checked={Boolean(draft.solve_cloudflare)} disabled={draft.scrapling_mode === "fetcher"} onChange={(e) => set("solve_cloudflare", e.target.checked)} />Giải Cloudflare challenge</label>
              <label className="flex items-center gap-2 py-1 text-[13px]"><Checkbox checked={Boolean(draft.network_idle)} disabled={draft.scrapling_mode === "fetcher"} onChange={(e) => set("network_idle", e.target.checked)} />Đợi mạng nhàn rỗi</label>
              <label className="flex items-center gap-2 py-1 text-[13px]"><Checkbox checked={Boolean(draft.dns_over_https)} disabled={draft.scrapling_mode === "fetcher"} onChange={(e) => set("dns_over_https", e.target.checked)} />DNS-over-HTTPS</label>
              <Field label="Số lần thử lại"><Input type="number" value={String(draft.retry_attempts ?? 3)} onChange={(e) => set("retry_attempts", e.target.value === "" ? 3 : Number(e.target.value))} /></Field>
              <Field label="Delay thử lại (giây)"><Input type="number" step={0.1} value={String(draft.retry_delay_seconds ?? 5)} onChange={(e) => set("retry_delay_seconds", e.target.value === "" ? 5 : Number(e.target.value))} /></Field>
              <Field label="Hệ số backoff"><Input type="number" step={0.1} value={String(draft.retry_backoff ?? 2)} onChange={(e) => set("retry_backoff", e.target.value === "" ? 2 : Number(e.target.value))} /></Field>
              <Field label="Delay thử lại tối đa (giây)"><Input type="number" value={String(draft.retry_max_delay_seconds ?? 120)} onChange={(e) => set("retry_max_delay_seconds", e.target.value === "" ? 120 : Number(e.target.value))} /></Field>
              <label className="flex items-center gap-2 py-1 text-[13px]"><Checkbox checked={Boolean(draft.retry_respect_retry_after)} onChange={(e) => set("retry_respect_retry_after", e.target.checked)} />Tôn trọng header Retry-After</label>
              <div className="md:col-span-2 lg:col-span-3">
                <Field label="Regex loại bỏ nội dung thừa" hint="1 pattern / dòng — loại bỏ dòng chứa quảng cáo/rác"><Textarea rows={4} value={String(draft.strip_patterns || "")} onChange={(e) => set("strip_patterns", e.target.value)} className="font-mono text-xs" spellCheck={false} /></Field>
              </div>
            </div>
          </fieldset>
        ) : null}
      </div>
    </Panel>
  );
}

/* ── Đặc tả field theo từng tab ──────────────────────────────────────── */

const NOVEL_FIELDS: FieldSpec<EbookSettings["novel"]>[] = [
  { key: "title", label: "Tiêu đề", kind: "text" },
  { key: "author", label: "Tác giả", kind: "text" },
  { key: "language", label: "Ngôn ngữ", kind: "text" },
  { key: "publisher", label: "Nhà xuất bản", kind: "text" },
  { key: "pubdate", label: "Ngày xuất bản", kind: "text", hint: "YYYY-MM-DD" },
  { key: "series", label: "Series", kind: "text" },
  { key: "series_index", label: "Thứ tự trong series", kind: "text" },
  { key: "identifier", label: "Identifier", kind: "text", hint: "Để trống để giữ giá trị tự sinh hiện có" },
  { key: "cover_url", label: "URL ảnh bìa", kind: "text", hint: "Lưu là tải về ngay; để trống để gỡ ảnh", wide: true },
  { key: "description", label: "Mô tả", kind: "textarea", wide: true },
  { key: "subjects", label: "Chủ đề", kind: "textarea", hint: "1 chủ đề / dòng", wide: true },
];

const READER_FIELDS: FieldSpec<EbookSettings["reader"]>[] = [
  { key: "url", label: "URL Reader", kind: "text", wide: true },
  { key: "service_key", label: "Service key", kind: "password", wide: true },
  { key: "reader_slug", label: "Slug trên Reader", kind: "text" },
  { key: "free_chapters", label: "Số chương đọc miễn phí", kind: "number" },
  { key: "batch_size", label: "Số chương / lần đẩy", kind: "number" },
  { key: "timeout_seconds", label: "Timeout (giây)", kind: "number" },
  { key: "push_anchors", label: "Đẩy kèm anchor điều hướng", kind: "checkbox" },
  { key: "published", label: "Công khai trên Reader", kind: "checkbox" },
];

const OUTPUT_FIELDS: FieldSpec<EbookSettings["output"]>[] = [
  { key: "data_dir", label: "Thư mục dữ liệu", kind: "text", wide: true },
  { key: "epub_path", label: "Đường dẫn EPUB", kind: "text", wide: true },
  { key: "crawl_max_workers", label: "Số luồng crawl (toàn hàng đợi)", kind: "number" },
  { key: "translate_max_workers", label: "Số luồng dịch (toàn hàng đợi)", kind: "number" },
];

/* ── Dịch API / Local MT / AI biên tập (giữ nguyên) ───────────────── */

const LOCAL_MT_MODELS = [
  { value: "hachimimt-60", label: "HachimiMT-60" },
  { value: "hachimimt-30", label: "HachimiMT-30" },
  { value: "moxhimt-60", label: "MoxhiMT-60" },
  { value: "moxhimt-30", label: "MoxhiMT-30" },
  { value: "hirashiba-medium", label: "HirashibaMT-Medium" },
  { value: "hirashiba-tiny", label: "HirashibaMT-Tiny" },
];

const LOCAL_MT_KEYS = LOCAL_MT_MODELS.map((item) => ({
  value: item.label,
  label: item.label,
}));

function TranslateTab({ slug, server, meta }: { slug: string; server: EbookSettings["translate"]; meta: EbookSettings["meta"] }) {
  const toast = useToast();
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const fields: FieldSpec<EbookSettings["translate"]>[] = [
    { key: "type", label: "Backend dịch", kind: "select", options: [{ value: "openai", label: "Dịch API OpenAI-compatible" }, { value: "localmt", label: "Local MT làm backend mặc định" }, { value: "none", label: "Không dịch" }] },
    { key: "preset", label: "Preset prompt", kind: "select", options: [{ value: "", label: "Không dùng preset" }, { value: "go", label: "Go" }, { value: "omniroute", label: "OmniRoute" }] },
    { key: "source_language", label: "Ngôn ngữ nguồn", kind: "select", options: [{ value: "", label: "Trung (mặc định)" }, { value: "en", label: "Anh" }, { value: "vi", label: "Việt (không cần dịch)" }] },
    { key: "target_language", label: "Ngôn ngữ đích", kind: "text", hint: "Mặc định: vi" },
    { key: "genre", label: "Thể loại", kind: "select", options: meta.genres.length ? meta.genres : [{ value: "auto", label: "auto" }] },
    { key: "tone", label: "Tông giọng", kind: "text" },
    { key: "pronoun_policy", label: "Chính sách xưng hô", kind: "select", options: [{ value: "contextual", label: "Theo ngữ cảnh" }, { value: "formal", label: "Trang trọng" }, { value: "modern_casual", label: "Hiện đại, đời thường" }] },
    { key: "title_mode", label: "Xử lý tiêu đề", kind: "select", options: [{ value: "creative", label: "Sáng tạo" }, { value: "literal", label: "Sát nghĩa" }] },
    { key: "han_viet_level", label: "Mức Hán Việt", kind: "select", options: [{ value: "light", label: "Nhẹ" }, { value: "balanced", label: "Cân bằng" }, { value: "heavy", label: "Đậm" }] },
    { key: "keep_paragraphs", label: "Giữ nguyên cách chia đoạn", kind: "checkbox" },
    { key: "delay_seconds", label: "Delay giữa các chương (giây)", kind: "number", step: 0.1 },
    { key: "max_workers", label: "Số luồng dịch song song", kind: "number" },
    { key: "batch_size", label: "Số chương / lần gọi API", kind: "number" },
    { key: "prompt_max_chars", label: "Giới hạn ký tự prompt", kind: "number", hint: "Mặc định hiệu lực: 20000" },
    { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
    { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
    { key: "chunk_max_chars", label: "Cắt chunk tại (ký tự)", kind: "number", hint: "0 = không cắt" },
    { key: "chunk_overlap_paragraphs", label: "Số đoạn chồng lấn giữa chunk", kind: "number" },
    { key: "auto_glossary", label: "Tự cập nhật glossary sau khi dịch API", kind: "checkbox" },
    { key: "use_idioms", label: "Dùng từ điển thành ngữ chung", kind: "checkbox" },
    { key: "ai_glossary_analysis", label: "Cho AI phân tích glossary từng chương", kind: "checkbox", hint: "Chậm hơn; chỉ bật khi cần học domain mới" },
    { key: "profile", label: "Profile dịch", kind: "text", hint: "Mặc định: traditional_cn_novel" },
    { key: "prompt_template", label: "Prompt dịch chương", kind: "textarea", wide: true },
    { key: "title_prompt_template", label: "Prompt dịch tiêu đề", kind: "textarea", wide: true },
  ];
  return (
    <SectionForm slug={slug} section="translate" title="Dịch API" hint="Engine, văn phong, glossary và giới hạn prompt; provider/model được quản lý ở mục “Provider AI cho truyện này” bên dưới và Dịch chung" fields={fields} server={server}
      renderExtraActions={(draft, setDraft) => (
        <>
          <Button size="sm" onClick={() => setPreviewOpen(true)}>Xem prompt toàn màn hình</Button>
          <Button size="sm" loading={loadingPrompts} onClick={async () => { setLoadingPrompts(true); try { const language = encodeURIComponent(String(draft.source_language ?? "")); const prompts = await api.get<Pick<EbookSettings["translate"], "prompt_template" | "title_prompt_template">>(`/settings/translate/default-prompts?source_language=${language}`); setDraft((current) => ({ ...current, ...prompts })); toast("Đã nạp lại prompt mặc định. Bấm Lưu để áp dụng."); } catch (error) { toast(error instanceof Error ? error.message : String(error), "error"); } finally { setLoadingPrompts(false); } }}>Nạp lại prompt</Button>
          <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="Xem và chỉnh sửa prompt dịch" fullscreen footer={<Button onClick={() => setPreviewOpen(false)}>Đóng</Button>}>
            <div className="grid min-h-full gap-4 lg:grid-cols-2">
              <Field label="Prompt dịch chương" hint="Các placeholder trong ngoặc nhọn được pipeline điền khi dịch."><Textarea value={String(draft.prompt_template ?? "")} onChange={(event) => setDraft((current) => ({ ...current, prompt_template: event.target.value }))} className="min-h-[55vh] resize-y font-mono text-xs leading-5 lg:min-h-full" spellCheck={false} /></Field>
              <Field label="Prompt dịch tiêu đề" hint="Prompt dùng riêng khi dịch tên truyện và tiêu đề chương."><Textarea value={String(draft.title_prompt_template ?? "")} onChange={(event) => setDraft((current) => ({ ...current, title_prompt_template: event.target.value }))} className="min-h-[40vh] resize-y font-mono text-xs leading-5 lg:min-h-full" spellCheck={false} /></Field>
            </div>
          </Modal>
        </>
      )}
    />
  );
}

function LocalMtTab({ slug, server }: { slug: string; server: EbookSettings["translate"] }) {
  const fields: FieldSpec<EbookSettings["translate"]>[] = [
    { key: "local_model", label: "Preset model", kind: "select", hint: "Chọn preset sẽ quyết định model thực tế bên dưới", options: [{ value: "", label: "Dùng model key thủ công" }, ...LOCAL_MT_MODELS] },
    { key: "hachimimt_model_key", label: "Model key", kind: "select", options: LOCAL_MT_KEYS },
    { key: "hachimimt_backend", label: "Runtime", kind: "select", hint: "Runtime hiện hỗ trợ CTranslate2", options: [{ value: "ctranslate2", label: "CTranslate2" }] },
    { key: "hachimimt_beam_size", label: "Beam size", kind: "number" },
    { key: "hachimimt_chunk_mode", label: "Chia nội dung theo", kind: "select", options: [{ value: "sentence", label: "Câu" }, { value: "paragraph", label: "Đoạn" }] },
    { key: "source_language", label: "Ngôn ngữ nguồn", kind: "text", hint: "Để trống cho Trung văn" },
    { key: "target_language", label: "Ngôn ngữ đích", kind: "text", hint: "Mặc định: vi" },
    { key: "delay_seconds", label: "Delay giữa các chương (giây)", kind: "number", step: 0.1 },
    { key: "max_workers", label: "Số chương chạy song song", kind: "number" },
    { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
    { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
    { key: "auto_cleanup_han", label: "Tự dọn Hán tự sót lại", kind: "checkbox" },
    { key: "cleanup_han_engine", label: "Engine dọn Hán tự", kind: "select", options: [{ value: "local_mt", label: "Local MT offline" }, { value: "openai", label: "AI biên tập" }] },
    { key: "cleanup_han_max_chars", label: "Giới hạn ký tự dọn Hán", kind: "number", hint: "Mặc định: 18000" },
    { key: "cleanup_han_retries", label: "Số lần thử lại dọn Hán", kind: "number" },
  ];
  return (
    <SectionForm slug={slug} section="translate" title="Local MT" hint="Dịch hoàn toàn offline; không gọi Base URL hoặc API key của AI" fields={fields} server={server}
      banner={<div className="flex flex-wrap items-center gap-2 border-b border-base-300 bg-success/10 px-4 py-2 text-[13px]"><Badge tone="celadon">Offline</Badge><span className="opacity-70">Action “Local MT” luôn ép engine Local MT, bất kể backend mặc định ở tab Dịch API.</span></div>}
    />
  );
}

function TranslateAiProviderPanel({ slug, ai }: { slug: string; ai: AiSettings }) {
  const toast = useToast();
  const { data: globalAi } = useGlobalAi();
  const saveProvider = useSaveSettings(slug, "ai");
  const modelQuery = useEbookModelOverrides(slug);
  const saveModels = useSaveEbookModelOverrides(slug);
  const [baseUrl, setBaseUrl] = useState(ai.base_url);
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState(ai.timeout_seconds);
  const [temperature, setTemperature] = useState(ai.temperature);
  const [translationModel, setTranslationModel] = useState("");
  const [assistantModel, setAssistantModel] = useState("");
  const [test, setTest] = useState<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string } | null>(null);
  const [modelsStatus, setModelsStatus] = useState("");
  useEffect(() => { setBaseUrl(ai.base_url); setTimeoutSeconds(ai.timeout_seconds); setTemperature(ai.temperature); }, [ai.base_url, ai.timeout_seconds, ai.temperature]);
  useEffect(() => { if (modelQuery.data) { setTranslationModel(modelQuery.data.translation_model); setAssistantModel(modelQuery.data.assistant_model); } }, [modelQuery.data]);
  const baseUrlForModel = baseUrl || globalAi?.base_url || "";
  const onTest = async () => { try { const r = await api.post<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string }>("/settings/ai/test", { body: { base_url: baseUrlForModel, api_key: apiKey || globalAi?.api_key || "", timeout_seconds: 15 } }); setTest(r); } catch (e) { setTest({ ok: false, error: e instanceof Error ? e.message : String(e) }); } };
  const onLoadModels = async () => { setModelsStatus("Đang tải danh sách model…"); const result = await fetchAndMergeModels(baseUrlForModel, apiKey || globalAi?.api_key || ""); setModelsStatus(result.error ?? `Đã tải ${result.count} model${result.total > result.count ? ` · ${result.total} trong cache` : ""}`); };
  const onLoadFromGlobal = () => { if (!globalAi) return; setBaseUrl(globalAi.base_url); setTimeoutSeconds(globalAi.timeout_seconds); setTemperature(globalAi.temperature); setTranslationModel(globalAi.translation_model); setAssistantModel(globalAi.assistant_model); };
  const onReset = async () => { try { await api.post(`/ebooks/${slug}/settings/ai/reset`); setBaseUrl(globalAi?.base_url ?? ""); setTimeoutSeconds(globalAi?.timeout_seconds ?? 120000); setTemperature(globalAi?.temperature ?? 0.7); setApiKey(""); setTranslationModel(""); setAssistantModel(""); toast("Đã reset AI riêng về mặc định chung (Dịch chung)."); } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); } };
  const onSave = async () => { try { await saveProvider.mutateAsync({ base_url: baseUrl, api_key: apiKey, timeout_seconds: timeoutSeconds, temperature, api_key_configured: ai.api_key_configured }, { onSuccess: () => toast("Đã lưu provider AI riêng cho truyện này.") }); await saveModels.mutateAsync({ translation_model: translationModel, assistant_model: assistantModel }, { onSuccess: () => toast("Đã lưu model AI riêng cho truyện này.") }); } catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); } };
  return (
    <Panel className="mt-4 overflow-hidden">
      <PanelHeader title="AI riêng cho truyện này (ghi đè Dịch chung)" hint="Mỗi truyện có thể dùng provider, API key, timeout, temperature và model riêng — ghi đè hoàn toàn config AI chung." actions={<div className="flex flex-wrap gap-2"><Button size="sm" onClick={onLoadModels}>Tải models</Button><Button size="sm" onClick={onTest}>Thử kết nối</Button><Button size="sm" variant="ghost" onClick={onLoadFromGlobal}>Nạp lại từ Dịch chung</Button><Button size="sm" variant="ghost" onClick={onReset}>Reset về chung</Button><Button size="sm" variant="primary" loading={saveProvider.isPending || saveModels.isPending} onClick={onSave}>Lưu AI riêng</Button></div>} />
      <div className="border-b border-base-300 bg-base-200/50 px-4 py-3 text-[13px]">
        <div className="flex flex-wrap items-center gap-2"><Badge tone={ai.api_key_configured ? "celadon" : "gold"}>{ai.api_key_configured ? "Đã có API key riêng" : "Chưa có API key riêng (kế thừa chung)"}</Badge><span className="opacity-70">Để trống API key khi lưu sẽ giữ nguyên secret hiện tại của truyện này.</span></div>
        {globalAi ? <p className="mt-2 opacity-70">Dịch chung — Base URL: <code>{globalAi.base_url}</code> · Translation: <code>{globalAi.translation_model || "(trống)"}</code> · Assistant: <code>{globalAi.assistant_model || "(trống)"}</code> · Timeout: {globalAi.timeout_seconds}s · Temp: {globalAi.temperature}</p> : null}
        {test ? <p className={clsx("mt-2", test.ok ? "text-success" : "text-error")} role="status">{test.ok ? `Kết nối OK · ${test.model_count} model · ${test.latency_ms}ms` : test.error}</p> : null}
        {modelsStatus ? <p className="mt-2 opacity-70" role="status">{modelsStatus}</p> : null}
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <div className="md:col-span-2"><Field label="Base URL" hint="OpenAI-compatible endpoint, ví dụ https://host/v1"><Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} spellCheck={false} /></Field></div>
        <Field label="API key" hint={ai.api_key_configured ? "Nhập giá trị mới để thay key hiện tại" : "Credential riêng cho truyện này; để trống giữ nguyên"}><Input type="password" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></Field>
        <Field label="Timeout (giây)"><Input type="number" min={1} value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} /></Field>
        <ModelField label="Model dịch chương" hint="Để trống = dùng model chung từ Dịch chung" value={translationModel} baseUrl={baseUrlForModel} onChange={(value) => setTranslationModel(String(value))} />
        <ModelField label="Model trợ lý" hint="Glossary, rewrite, cleanup, Reader và metadata AI. Để trống = dùng chung" value={assistantModel} baseUrl={baseUrlForModel} onChange={(value) => setAssistantModel(String(value))} />
        <Field label="Temperature" hint="0–2"><Input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></Field>
      </div>
    </Panel>
  );
}

function OpdsTab({ server }: { server: OpdsSettings }) {
  const toast = useToast();
  const [values, setValues] = useState(server);
  useEffect(() => setValues(server), [server]);
  const save = useMutation({
    mutationFn: () => api.post<{ saved: boolean; opds: OpdsSettings }>("/api/ui/settings/opds", { body: values }),
    onSuccess: (result) => { setValues(result.opds); toast("Đã lưu cấu hình OPDS."); },
    onError: (error) => toast(error instanceof Error ? error.message : String(error), "error"),
  });
  return (
    <Panel>
      <PanelHeader title="OPDS" hint="Catalog dùng cho Readest và các ứng dụng đọc sách tương thích OPDS" actions={<Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Lưu OPDS</Button>} />
      <div className="border-b border-base-300 bg-base-200/50 px-4 py-3 text-[13px]"><Badge tone={values.token_configured ? "celadon" : "gold"}>{values.token_configured ? "Đã có token" : "Chưa có token"}</Badge><span className="ml-2 opacity-70">Catalog: <code>/opds</code>. Để trống token khi lưu sẽ giữ nguyên token hiện tại.</span></div>
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <Field label="Token truy cập" hint="Nhập giá trị mới chỉ khi muốn thay token hiện tại"><Input type="password" autoComplete="new-password" value={values.token} onChange={(event) => setValues((current) => ({ ...current, token: event.target.value }))} /></Field>
        <div className="flex items-end pb-1"><label className="flex items-center gap-2 text-[13px]"><Checkbox checked={values.auto_build} onChange={(event) => setValues((current) => ({ ...current, auto_build: event.target.checked }))} />Tự build lại EPUB khi mở catalog</label></div>
        <div className="md:col-span-2"><Field label="CORS origins" hint="Mỗi origin một dòng, ví dụ https://readest.com"><Textarea rows={5} spellCheck={false} value={values.cors_origins} onChange={(event) => setValues((current) => ({ ...current, cors_origins: event.target.value }))} /></Field></div>
      </div>
    </Panel>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

const TABS = [
  { key: "novel", label: "Truyện" },
  { key: "source", label: "Nguồn" },
  { key: "translate", label: "Dịch" },
  { key: "localmt", label: "Local MT" },
  { key: "opds", label: "OPDS" },
  { key: "reader", label: "Reader" },
  { key: "output", label: "Đầu ra" },
] as const;

export function SettingsPage() {
  const { slug = "" } = useParams();
  const { data, isPending, error } = useEbookSettings(slug);
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("translate");

  if (isPending) {
    return (
      <Page title="Đang tải cài đặt" loading loadingLabel="Đang đọc cấu hình">
        {null}
      </Page>
    );
  }
  if (error || !data) {
    return (
      <Page title="Không mở được cài đặt">
        <Panel>
          <EmptyState title="Không đọc được cấu hình truyện này" hint={error instanceof Error ? error.message : String(error)} />
        </Panel>
      </Page>
    );
  }
  const sourceBanner = data.meta.source_name ? (
    <div className="flex flex-wrap items-center gap-2 border-b border-base-300 bg-base-200/50 px-4 py-2 text-[13px]">
      <span className="opacity-70">Nguồn: <span className="font-medium">{data.meta.source_name}</span>{data.meta.source_detected ? " (tự nhận diện theo URL)" : ""}</span>
      {data.meta.overridden_fields.length > 0 ? <Badge tone="gold">{data.meta.overridden_fields.length} trường đã ghi đè nguồn</Badge> : null}
    </div>
  ) : null;

  return (
    <Page title="Cài đặt" hint={<>{slug} · lưu theo từng mục, không cần lưu tất cả cùng lúc</>}>
      <div role="tablist" className="tabs tabs-border mb-4">
        {TABS.map((t) => (
          <button key={t.key} role="tab" type="button" className={clsx("tab", tab === t.key && "tab-active")} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "novel" ? <SectionForm slug={slug} section="novel" title="Truyện" hint="Metadata dùng khi build EPUB" fields={NOVEL_FIELDS} server={data.novel} /> : null}
      {tab === "source" ? <SourceTab slug={slug} server={data.source} banner={sourceBanner} /> : null}
      {tab === "translate" ? <><TranslateTab slug={slug} server={data.translate} meta={data.meta} /><TranslateAiProviderPanel slug={slug} ai={data.ai} /></> : null}
      {tab === "localmt" ? <LocalMtTab slug={slug} server={data.translate} /> : null}
      {tab === "opds" ? <OpdsTab server={data.opds} /> : null}
      {tab === "reader" ? <SectionForm slug={slug} section="reader" title="Reader" hint="Đẩy bản dịch sang app đọc novel-reader" fields={READER_FIELDS} server={data.reader} /> : null}
      {tab === "output" ? <SectionForm slug={slug} section="output" title="Đầu ra" hint="Vị trí lưu dữ liệu và số luồng xử lý" fields={OUTPUT_FIELDS} server={data.output} /> : null}

      <p className="mt-3 text-xs opacity-50">Đồng bộ vào nguồn dùng chung, tải ảnh bìa từ máy và reset override vẫn chưa có mặt trong giao diện mới — tạm thời chỉnh thẳng trong file cấu hình nếu cần.</p>
    </Page>
  );
}
