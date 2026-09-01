import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import clsx from "clsx";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";

/* ── helpers ─────────────────────────────────────────────────────── */

function countMatches(html: string, selector: string): number {
  if (!selector.trim() || !html.trim()) return 0;
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    return doc.querySelectorAll(selector).length;
  } catch {
    return -1;
  }
}

function buildSelector(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  let depth = 0;
  while (cur && cur.tagName.toLowerCase() !== "html" && depth < 4) {
    const tag = cur.tagName.toLowerCase();
    const id = cur.id ? `#${CSS.escape(cur.id)}` : "";
    if (id) {
      parts.unshift(`${tag}${id}`);
      break;
    }
    const cls = (cur.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).join(".");
    const base = cls ? `${tag}.${cls.split(".").map(CSS.escape).join(".")}` : tag;
    // disambiguate siblings with same tag/class
    const parent = cur.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName && (cls ? (c.getAttribute("class") || "").trim().split(/\s+/).slice(0, 2).join(".") === cls.split(".").slice(1).join(".") : true));
      if (siblings.length > 1) {
        const idx = siblings.indexOf(cur) + 1;
        parts.unshift(`${base}:nth-child(${idx})`);
      } else {
        // use :nth-child if there are many children - gives stable selector
        const allSibs = Array.from(parent.children);
        if (allSibs.length > 1) {
          const idxAll = allSibs.indexOf(cur) + 1;
          // only add nth if needed for uniqueness – keep short
          if (allSibs.length > 6) parts.unshift(`${base}:nth-child(${idxAll})`);
          else parts.unshift(base);
        } else parts.unshift(base);
      }
    } else parts.unshift(base);
    cur = cur.parentElement;
    depth += 1;
  }
  return parts.join(" > ");
}

function sanitizeHtml(html: string): string {
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("script, style, noscript, iframe, template, canvas, form, svg").forEach((n) => n.remove());
    // strip event handlers
    doc.querySelectorAll<HTMLElement>("*").forEach((el) => {
      [...el.attributes].forEach((attr) => {
        if (attr.name.startsWith("on")) el.removeAttribute(attr.name);
      });
    });
    return doc.body ? doc.body.innerHTML : html.slice(0, 120_000);
  } catch {
    return html.slice(0, 120_000);
  }
}

function positionalVariant(selector: string, which: "first" | "last" | "n2" | "n3" | "clear"): string {
  const base = selector.trim().replace(/:(first-child|last-child|nth-child\(\d+\)|first-of-type|last-of-type|nth-of-type\(\d+\))(\s*>\s*)?/g, "").trim();
  if (!base) return selector;
  if (which === "clear") return base;
  if (which === "first") return `${base}:first-child`;
  if (which === "last") return `${base}:last-child`;
  if (which === "n2") return `${base}:nth-child(2)`;
  if (which === "n3") return `${base}:nth-child(3)`;
  return base;
}

/* ── Match badge ─────────────────────────────────────────────────── */

function MatchBadge({ html, selector, expectOne }: { html: string; selector: string; expectOne?: boolean }) {
  const cnt = useMemo(() => countMatches(html, selector), [html, selector]);
  if (!selector.trim()) return <span className="text-xs opacity-40">chưa nhập</span>;
  if (cnt === -1) return <Badge tone="vermilion">lỗi cú pháp</Badge>;
  if (cnt === 0) return <Badge tone="vermilion">0 khớp — rỗng</Badge>;
  if (expectOne && cnt > 1) return <Badge tone="gold">⚠️ {cnt} khớp — dự kiến 1</Badge>;
  if (cnt > 10) return <Badge tone="gold">⚠️ {cnt} khớp — quá rộng</Badge>;
  if (cnt > 1) return <Badge tone="gold">{cnt} khớp</Badge>;
  return <Badge tone="celadon">{cnt} khớp — OK</Badge>;
}

function RegexBadge({ pattern, sampleLinks }: { pattern: string; sampleLinks: string[] }) {
  if (!pattern.trim()) return <span className="text-xs opacity-40">trống</span>;
  if (pattern.trim() === ".*" || pattern.trim() === ".+" || pattern.trim() === "") {
    return <Badge tone="vermilion">⚠️ khớp toàn bộ — nguy hiểm</Badge>;
  }
  try {
    const re = new RegExp(pattern);
    const hits = sampleLinks.filter((u) => re.test(u)).length;
    if (sampleLinks.length === 0) return <Badge tone="indigo">{hits} test</Badge>;
    if (hits === 0) return <Badge tone="vermilion">0/{sampleLinks.length} khớp</Badge>;
    if (hits === sampleLinks.length && sampleLinks.length > 5) return <Badge tone="gold">⚠️ {hits}/{sampleLinks.length} khớp hết — quá rộng</Badge>;
    return <Badge tone={hits > 0 ? "celadon" : "vermilion"}>{hits}/{sampleLinks.length} khớp</Badge>;
  } catch (e) {
    return <Badge tone="vermilion">lỗi regex</Badge>;
  }
}

/* ── DOM Picker Modal ────────────────────────────────────────────── */

export function DomPickerModal({
  open,
  onClose,
  html,
  selector,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  html: string;
  selector: string;
  onPick: (sel: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverPath, setHoverPath] = useState("");
  const sanitized = useMemo(() => sanitizeHtml(html), [html]);

  // highlight matches of current selector
  useEffect(() => {
    if (!open || !containerRef.current) return;
    const root = containerRef.current;
    // clear previous outlines
    root.querySelectorAll<HTMLElement>("[data-n2e-hl]").forEach((el) => {
      el.style.outline = "";
      el.removeAttribute("data-n2e-hl");
    });
    if (!selector.trim()) return;
    try {
      root.querySelectorAll<HTMLElement>(selector).forEach((el) => {
        el.style.outline = "2px solid oklch(0.65 0.18 250)";
        el.style.outlineOffset = "1px";
        el.setAttribute("data-n2e-hl", "1");
      });
    } catch { /* ignore invalid */ }
  }, [open, selector, sanitized]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const target = e.target as Element;
    if (!target || !containerRef.current || !containerRef.current.contains(target)) return;
    // ignore clicks on wrapper itself
    if (target === containerRef.current) return;
    const sel = buildSelector(target);
    onPick(sel);
    // keep modal open so user can test immediately; caller may close on confirm
  }, [onPick]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const target = e.target as Element;
    if (!target || !containerRef.current || !containerRef.current.contains(target)) return;
    setHoverPath(buildSelector(target));
  }, []);

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title="Chọn selector từ DOM" wide
      footer={<>
        <span className="mr-auto text-xs opacity-60 hidden sm:inline">Click vào phần tử trong khung để sinh selector · hover xem đường dẫn</span>
        <Button onClick={onClose}>Đóng</Button>
      </>}
    >
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="opacity-60">Đang thử:</span> <code className="rounded bg-base-200 px-1.5 py-0.5 font-mono text-xs">{selector || "—"}</code>
          <MatchBadge html={html} selector={selector} />
        </div>
        {hoverPath ? <div className="truncate rounded bg-base-200 px-2 py-1 font-mono text-[11px] opacity-70">hover: {hoverPath}</div> : null}
        <div
          ref={containerRef}
          className="max-h-[50vh] overflow-auto rounded-box border border-base-300 p-2 text-base-content [&_a]:text-primary [&_a]:underline"
          onClick={handleClick}
          onMouseMove={handleMouseMove}
          dangerouslySetInnerHTML={{ __html: sanitized || '<p class="opacity-50 p-4">DOM trống — hãy tải lại trang.</p>' }}
        />
        <p className="text-[11px] opacity-50">Tip: bấm vào tiêu đề, khối nội dung, hoặc 1 link chương để lấy selector gợi ý. Sau đó dùng nút Đầu/Cuối/Thứ 2 bên ngoài để tinh chỉnh.</p>
      </div>
    </Modal>
  );
}

/* ── Client-side heuristic ranking (mirror of selector_ai.py finders) ──
   Không tốn token/AI — chỉ duyệt DOM đã tải sẵn trong state.                */

type CandidateKind = "link-wrapper" | "text-wrapper" | "heading" | "keyword" | "image" | "next-link";

interface RankedCandidate {
  selector: string;
  detail: string;
}

const DROP_TAG_SET = new Set(["script", "style", "noscript", "svg", "iframe", "template", "canvas", "form"]);
const TITLE_KEYWORDS = ["title", "bookname", "book-name", "chapter-name", "chaptername"];
const IMAGE_KEYWORDS = ["cover", "book-img", "bookimg", "fm", "pic", "thumb"];
const NEXT_KEYWORDS = ["sau", "next", "\u00bb", "\u4e0b\u4e00\u9875", "\u4e0b\u4e00\u7ae0", "\u4e0b\u4e00\u9801", ">>"];

function idClassText(el: Element): string {
  const id = el.getAttribute("id") || "";
  const cls = el.getAttribute("class") || "";
  const itemprop = el.getAttribute("itemprop") || "";
  return `${id} ${cls} ${itemprop}`.toLowerCase();
}

function previewText(el: Element, len = 40): string {
  const raw = (el.textContent || "").replace(/\s+/g, " ").trim();
  return raw.slice(0, len);
}

function linkCount(el: Element): number {
  return el.querySelectorAll("a[href]").length;
}

function textLen(el: Element): number {
  const raw = (el.textContent || "").replace(/\s+/g, " ").trim();
  return raw.length;
}

function rankLinkWrapperCandidates(doc: Document, maxCandidates = 3): RankedCandidate[] {
  const body = doc.body || doc.documentElement;
  if (!body) return [];
  const elements = Array.from(body.querySelectorAll("*")) as Element[];
  const maxLinks = Math.max(0, ...elements.map(linkCount));
  if (maxLinks < 3) return [];
  const threshold = Math.max(3, Math.floor(maxLinks * 0.8));
  let cur: Element = body;
  for (;;) {
    const nxt = Array.from(cur.children).find((c) => linkCount(c as Element) >= threshold) as Element | undefined;
    if (!nxt) break;
    cur = nxt;
  }
  const ranked = elements.filter((el) => linkCount(el) >= 3).sort((a, b) => linkCount(b) - linkCount(a));
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of [cur, ...ranked]) {
    const sel = buildSelector(el);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    const hrefs = Array.from(el.querySelectorAll("a[href]"))
      .slice(0, 2)
      .map((a) => (a.getAttribute("href") || "").trim())
      .filter(Boolean);
    const detail = `${linkCount(el)} link${hrefs.length ? `, mẫu: ${hrefs.join(", ")}` : ""}`;
    out.push({ selector: sel, detail });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

function rankTextWrapperCandidates(doc: Document, maxCandidates = 3): RankedCandidate[] {
  const body = doc.body || doc.documentElement;
  if (!body) return [];
  const elements = Array.from(body.querySelectorAll("*")) as Element[];
  const maxText = Math.max(0, ...elements.map(textLen));
  if (maxText < 40) return [];
  const threshold = Math.floor(maxText * 0.8);
  let cur: Element = body;
  for (;;) {
    const nxt = Array.from(cur.children).find((c) => textLen(c as Element) >= threshold) as Element | undefined;
    if (!nxt) break;
    cur = nxt;
  }
  const ranked = elements.filter((el) => el.querySelectorAll("p").length >= 3).sort((a, b) => textLen(b) - textLen(a));
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of [cur, ...ranked]) {
    const sel = buildSelector(el);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    const pcount = el.querySelectorAll("p").length;
    out.push({ selector: sel, detail: `${textLen(el)} ký tự, ${pcount} <p>, mở đầu: "${previewText(el, 40)}"` });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

function rankHeadingCandidates(doc: Document, maxCandidates = 3): RankedCandidate[] {
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of Array.from(doc.querySelectorAll("h1"))) {
    const sel = buildSelector(el as Element);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    out.push({ selector: sel, detail: `"${previewText(el as Element)}"` });
    if (out.length >= maxCandidates) return out;
  }
  for (const el of Array.from(doc.querySelectorAll("*"))) {
    if (!TITLE_KEYWORDS.some((k) => idClassText(el as Element).includes(k))) continue;
    const sel = buildSelector(el as Element);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    out.push({ selector: sel, detail: `"${previewText(el as Element)}"` });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

function rankKeywordCandidates(doc: Document, keywords: string[], maxCandidates = 3): RankedCandidate[] {
  if (!keywords.length) return [];
  const lowers = keywords.map((k) => k.toLowerCase());
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of Array.from(doc.querySelectorAll("*"))) {
    if (DROP_TAG_SET.has(el.tagName.toLowerCase())) continue;
    if (!lowers.some((k) => idClassText(el as Element).includes(k))) continue;
    const sel = buildSelector(el as Element);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    out.push({ selector: sel, detail: `"${previewText(el as Element)}"` });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

function rankImageCandidates(doc: Document, keywords: string[] = IMAGE_KEYWORDS, maxCandidates = 3): RankedCandidate[] {
  const lowers = keywords.map((k) => k.toLowerCase());
  const score = (el: Element) => {
    const parent = el.parentElement;
    const parentText = parent ? idClassText(parent) : "";
    const selfText = idClassText(el);
    return lowers.some((k) => selfText.includes(k) || parentText.includes(k)) ? 1 : 0;
  };
  const imgs = Array.from(doc.querySelectorAll("img")).sort((a, b) => score(b as Element) - score(a as Element));
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of imgs) {
    const sel = buildSelector(el as Element);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    const src = (el.getAttribute("src") || el.getAttribute("data-src") || "").slice(0, 80);
    out.push({ selector: sel, detail: `src=${src}` });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

function rankNextLinkCandidates(doc: Document, maxCandidates = 3): RankedCandidate[] {
  const seen = new Set<string>();
  const out: RankedCandidate[] = [];
  for (const el of Array.from(doc.querySelectorAll("a[href]"))) {
    const text = (el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    const idc = idClassText(el as Element);
    if (!NEXT_KEYWORDS.some((k) => text.includes(k) || idc.includes(k))) continue;
    const sel = buildSelector(el as Element);
    if (!sel || seen.has(sel)) continue;
    seen.add(sel);
    out.push({ selector: sel, detail: `text="${text.slice(0, 30)}"` });
    if (out.length >= maxCandidates) break;
  }
  return out;
}

export function rankCandidates(html: string, kind: CandidateKind | undefined, keywords?: string[]): RankedCandidate[] {
  if (!kind || !html.trim()) return [];
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll(Array.from(DROP_TAG_SET).join(",")).forEach((n) => n.remove());
    switch (kind) {
      case "link-wrapper":
        return rankLinkWrapperCandidates(doc);
      case "text-wrapper":
        return rankTextWrapperCandidates(doc);
      case "heading":
        return rankHeadingCandidates(doc);
      case "keyword":
        return rankKeywordCandidates(doc, keywords || []);
      case "image":
        return rankImageCandidates(doc, keywords && keywords.length ? keywords : IMAGE_KEYWORDS);
      case "next-link":
        return rankNextLinkCandidates(doc);
      default:
        return [];
    }
  } catch {
    return [];
  }
}

/* ── Selector field ──────────────────────────────────────────────── */

export function SelectorField({
  label,
  hint,
  value,
  onChange,
  html,
  placeholder,
  expectOne,
  wrapperNote,
  candidateKind,
  candidateKeywords,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  html: string;
  placeholder?: string;
  expectOne?: boolean;
  wrapperNote?: string;
  candidateKind?: CandidateKind;
  candidateKeywords?: string[];
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const cnt = useMemo(() => countMatches(html, value), [html, value]);
  const showWarning = value.trim() && (cnt === 0 || cnt === -1 || (expectOne && cnt > 1) || cnt > 10);
  const suggestions = useMemo(
    () => rankCandidates(html, candidateKind, candidateKeywords),
    [html, candidateKind, candidateKeywords],
  );

  return (
    <div className="space-y-1">
      <Field label={<span className="inline-flex items-center gap-2">{label} {wrapperNote ? <Badge tone="indigo" className="normal-case font-normal tracking-normal">{wrapperNote}</Badge> : null}</span>} hint={hint}>
        <div className="join w-full">
          <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} spellCheck={false} className={clsx("join-item flex-1 min-w-0 font-mono text-xs", showWarning && "input-error")} />
          <Button size="sm" className="join-item shrink-0" onClick={() => setPickerOpen(true)} disabled={!html} title={html ? "Chọn trực tiếp từ DOM đã tải" : "Tải DOM trước"}>
            Chọn từ DOM
          </Button>
        </div>
      </Field>
      {suggestions.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] opacity-50">gợi ý:</span>
          {suggestions.map((c) => (
            <button
              key={c.selector}
              type="button"
              className="btn btn-xs btn-soft normal-case font-mono text-xs"
              title={c.detail}
              onClick={() => onChange(c.selector)}
            >
              {c.selector}
            </button>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-1.5">
        <MatchBadge html={html} selector={value} expectOne={expectOne} />
        <span className="text-[11px] opacity-50">vị trí:</span>
        <div className="join">
          {(["first", "last", "n2", "n3", "clear"] as const).map((k) => (
            <button key={k} type="button" className="btn btn-xs join-item" title={k === "clear" ? "Xóa hậu tố vị trí" : `Thêm :${k}`} onClick={() => onChange(positionalVariant(value || ".item", k))}>
              {k === "first" ? "Đầu" : k === "last" ? "Cuối" : k === "n2" ? "Thứ 2" : k === "n3" ? "Thứ 3" : "Xóa"}
            </button>
          ))}
        </div>
      </div>
      {showWarning && cnt === 0 ? <p className="text-xs text-error">Không khớp phần tử nào — selector không tìm thấy trong DOM đã tải.</p> : null}
      {showWarning && cnt !== 0 && cnt !== -1 ? <p className="text-xs text-warning">⚠️ Khớp {cnt} phần tử — hãy thu hẹp wrapper (thêm class/id cha) hoặc dùng nút vị trí bên trên.</p> : null}
      {cnt === -1 ? <p className="text-xs text-error">Cú pháp selector không hợp lệ.</p> : null}
      <DomPickerModal open={pickerOpen} onClose={() => setPickerOpen(false)} html={html} selector={value} onPick={(sel) => onChange(sel)} />
    </div>
  );
}

export interface RegexQuickPattern {
  label: string;
  value: string;
  title: string;
}

const DEFAULT_QUICK_PATTERNS: RegexQuickPattern[] = [
  { label: ".*", value: ".*", title: "Khớp tất cả" },
  { label: "/\\d+\\.html$", value: "/\\d+\\.html$", title: "ID số + .html" },
  { label: "/chuong-\\d+", value: "/chuong-\\d+", title: "chuong-123" },
  { label: "/book/…", value: "/book/\\d+/\\d+\\.html$", title: "/book/1/2.html" },
];

export function RegexField({
  label,
  hint,
  value,
  onChange,
  sampleLinks,
  placeholder,
  quick,
  allowEmpty,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  sampleLinks: string[];
  placeholder?: string;
  quick?: RegexQuickPattern[];
  /** Cho phép rỗng không báo cảnh báo (vd regex dự phòng — rỗng = bỏ qua). */
  allowEmpty?: boolean;
}) {
  const isWildcard = value.trim() === ".*" || value.trim() === ".+";
  const isEmpty = !value.trim();
  const quicks = quick ?? DEFAULT_QUICK_PATTERNS;
  return (
    <div className="space-y-1">
      <Field label={label} hint={hint}>
        <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} spellCheck={false} className={clsx("font-mono text-xs w-full", isWildcard && "input-warning")} />
      </Field>
      <div className="flex flex-wrap items-center gap-1.5">
        <RegexBadge pattern={value} sampleLinks={sampleLinks} />
        <span className="text-[11px] opacity-50">mẫu nhanh:</span>
        <div className="join">
          {quicks.map((q) => (
            <button key={q.value} type="button" className="btn btn-xs join-item" onClick={() => onChange(q.value)} title={q.title}>
              {q.label}
            </button>
          ))}
        </div>
      </div>
      {isWildcard ? <p className="text-xs text-warning">⚠️ Regex này khớp TOÀN BỘ link trong trang — sẽ crawl cả menu/nav. Hãy thu hẹp (vd <code>/chuong-\d+\.html$</code>).</p> : null}
      {isEmpty && !allowEmpty ? <p className="text-xs text-warning">⚠️ Regex trống — mọi link đều lọt qua. Hãy thu hẹp hoặc giữ ".*" nếu trang chỉ có link chương.</p> : null}
      {sampleLinks.length > 0 ? <p className="text-[11px] opacity-50 truncate">Mẫu: {sampleLinks.slice(0, 3).join(" · ")} {sampleLinks.length > 3 ? `+${sampleLinks.length - 3}` : ""}</p> : null}
    </div>
  );
}

/* ── Dom Inspector Panel — dual DOM (TOC + Chapter), overwrite on reload ── */

type DomSnapshot = { html: string; sampleLinks: string[]; url: string };

export function DomInspector({
  tocUrl,
  chapterUrl,
  scraplingMode,
  onDom,
  html,
  sampleLinks,
  toc,
  chapter,
}: {
  tocUrl: string;
  chapterUrl?: string;
  scraplingMode: string;
  onDom: (info: { html: string; hrefs: string[]; sampleLinks: string[]; url: string; which: "toc" | "chapter" }) => void;
  html?: string;
  sampleLinks?: string[];
  toc?: DomSnapshot | null;
  chapter?: DomSnapshot | null;
}) {
  // dual storage — prefer explicit toc/chapter props, fallback to legacy html/sampleLinks
  const tocSnap = toc !== undefined ? toc : (html ? { html: html || "", sampleLinks: sampleLinks || [], url: tocUrl } : null);
  const chapSnap = chapter !== undefined ? chapter : null;

  const [tocInput, setTocInput] = useState(tocUrl);
  const [chapInput, setChapInput] = useState(chapterUrl || tocUrl);
  const [tocLoading, setTocLoading] = useState(false);
  const [chapLoading, setChapLoading] = useState(false);
  const [tocError, setTocError] = useState("");
  const [chapError, setChapError] = useState("");

  // Đồng bộ URL từ preset/preset change — nhưng không ghi đè nếu đã có snapshot hoặc user đã sửa input
  useEffect(() => {
    if (!tocSnap?.html) setTocInput(tocUrl);
  }, [tocUrl, tocSnap?.html]);
  useEffect(() => {
    if (!chapSnap?.html) setChapInput(chapterUrl || tocUrl);
  }, [chapterUrl, tocUrl, chapSnap?.html]);
  // Khi đổi sang preset khác (snapshot thay đổi) mà snapshot mới có URL khác — nạp lại URL từ snapshot
  useEffect(() => {
    if (tocSnap?.url) setTocInput(tocSnap.url);
  }, [tocSnap?.url]);
  useEffect(() => {
    if (chapSnap?.url) setChapInput(chapSnap.url);
  }, [chapSnap?.url]);

  const fetchDom = async (which: "toc" | "chapter") => {
    const url = (which === "toc" ? tocInput : chapInput).trim();
    if (!url) { (which === "toc" ? setTocError : setChapError)("Nhập URL trước."); return; }
    const setLoading = which === "toc" ? setTocLoading : setChapLoading;
    const setError = which === "toc" ? setTocError : setChapError;
    setLoading(true); setError("");
    try {
      const res = await api.post<{ ok: boolean; html: string; hrefs: string[]; sample_links: string[]; url: string; truncated: boolean }>(
        "/api/ui/sources/inspect",
        { body: { url, scrapling_mode: scraplingMode } },
      );
      onDom({ html: res.html, hrefs: res.hrefs, sampleLinks: res.sample_links, url: res.url, which });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  };

  const Card = ({
    which,
    title,
    hint,
    snap,
    input,
    setInput,
    loading,
    error,
    onFetch,
  }: {
    which: "toc" | "chapter";
    title: string;
    hint: string;
    snap: DomSnapshot | null | undefined;
    input: string;
    setInput: (v: string) => void;
    loading: boolean;
    error: string;
    onFetch: () => void;
  }) => (
    <div className="rounded-box border border-base-300 bg-base-100 p-3 space-y-2 flex flex-col">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold tracking-wide">{title}</span>
        {snap?.html ? (
          <Badge tone="celadon" className="shrink-0">{Math.round(snap.html.length / 1024)} KB · {snap.sampleLinks.length} link</Badge>
        ) : (
          <Badge tone="gold" className="shrink-0">Chưa có</Badge>
        )}
      </div>
      <p className="text-[11px] opacity-50 leading-relaxed">{hint}</p>
      <div className="join w-full">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={which === "toc" ? "https://.../muc-luc" : "https://.../chuong-1.html"}
          spellCheck={false}
          className="join-item flex-1 min-w-0 font-mono text-xs"
        />
        <Button size="sm" variant={snap?.html ? "neutral" : "primary"} loading={loading} onClick={onFetch} className="join-item shrink-0">
          {snap?.html ? "Ghi đè" : "Tải DOM"}
        </Button>
      </div>
      {error ? <p className="text-xs text-error">{error}</p> : null}
      {snap?.html ? (
        <>
          <p className="text-[11px] opacity-60 truncate">Đã lưu: <span className="font-mono">{snap.url}</span></p>
          {snap.sampleLinks.length > 0 ? (
            <div className="rounded bg-base-200 px-2 py-1.5 text-[11px] leading-relaxed">
              <span className="opacity-60">Mẫu link ({snap.sampleLinks.length}):</span>{" "}
              <span className="font-mono break-all">{snap.sampleLinks.slice(0, 2).join(" · ")}</span>
              {snap.sampleLinks.length > 2 ? <span className="opacity-50"> +{snap.sampleLinks.length - 2}</span> : null}
            </div>
          ) : (
            <p className="text-[11px] opacity-40">Không phát hiện link mẫu trong DOM này.</p>
          )}
        </>
      ) : (
        <p className="text-[11px] opacity-40">Nhập URL rồi bấm “Tải DOM” — tải lại sẽ <b>ghi đè</b> snapshot cũ.</p>
      )}
    </div>
  );

  const hasAny = Boolean(tocSnap?.html || chapSnap?.html);

  return (
    <div className="rounded-box border border-base-300 bg-base-100 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-base-300 bg-base-200/60 px-3 py-2">
        <span className="text-xs font-semibold tracking-wide">Phòng thí nghiệm DOM</span>
        <span className="hidden sm:inline text-[11px] opacity-50">— lưu HTML thực tế để đếm khớp &amp; “Chọn từ DOM”</span>
        <span className="flex-1" />
        {hasAny ? (
          <span className="text-[11px] opacity-60">
            {tocSnap?.html ? "TOC ✓" : "TOC —"} · {chapSnap?.html ? "Chương ✓" : "Chương —"}
          </span>
        ) : (
          <Badge tone="gold">Chưa có DOM</Badge>
        )}
      </div>
      <div className="p-3 space-y-2">
        <p className="text-xs opacity-60 leading-relaxed">
          Tải <b>Mục lục</b> và <b>Chương mẫu</b> riêng biệt. Mỗi lần “Tải DOM” sẽ <b>ghi đè</b> snapshot cũ — các ô selector phía dưới tự động đếm khớp, tô cảnh báo và cho phép “Chọn từ DOM” ngay.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <Card which="toc" title="📑 Mục lục" hint="Dùng cho: wrapper mục lục, regex lọc link, title/author/desc/cover" snap={tocSnap} input={tocInput} setInput={setTocInput} loading={tocLoading} error={tocError} onFetch={() => fetchDom("toc")} />
          <Card which="chapter" title="📄 Chương mẫu" hint="Dùng cho: wrapper nội dung, tiêu đề chương, phân trang chương" snap={chapSnap} input={chapInput} setInput={setChapInput} loading={chapLoading} error={chapError} onFetch={() => fetchDom("chapter")} />
        </div>
      </div>
    </div>
  );
}

/* Wrapper grouping hint */
export function WrapperHint() {
  return (
    <div className="rounded-box border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-relaxed">
      <span className="font-semibold">Cách wrapper + regex phối hợp:</span> <span className="opacity-80">Crawler chỉ xét các <code className="px-1 py-0.5 rounded bg-base-200">&lt;a&gt;</code> NẰM TRONG wrapper <code className="px-1 py-0.5 rounded bg-base-200">toc_selector</code>, rồi mới lọc bằng <code className="px-1 py-0.5 rounded bg-base-200">chapter_link_pattern</code>. Thu hẹp wrapper (vd <code>#list</code>) và regex cụ thể (vd <code>/chuong-\d+\.html$</code>) sẽ loại menu/nav/footer.</span>
    </div>
  );
}

/* ── Image URL extraction (cho regex ảnh bìa) ────────────────────── */

/** Trích các URL ảnh từ DOM snapshot — img src/srcset + lazy-load attrs +
 *  background-image inline + <source srcset>. Thứ tự xuất hiện trong trang. */
export function extractImageUrls(html: string, baseUrl: string, max = 40): string[] {
  if (!html.trim()) return [];
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const out: string[] = [];
    const push = (raw: string) => {
      const u = raw.trim();
      if (!u) return;
      let full: string;
      try {
        full = new URL(u, baseUrl || undefined).href;
      } catch {
        full = u;
      }
      if (!out.includes(full)) out.push(full);
    };
    for (const img of Array.from(doc.querySelectorAll("img"))) {
      for (const attr of ["src", "data-src", "data-original", "data-lazy-src"]) {
        push(img.getAttribute(attr) || "");
      }
      const srcset = img.getAttribute("srcset") || "";
      for (const part of srcset.split(",")) push(part.trim().split(" ")[0] || "");
    }
    for (const el of Array.from(doc.querySelectorAll("[style*='background'], source"))) {
      const style = `${el.getAttribute("style") || ""} ${el.getAttribute("srcset") || ""}`;
      for (const m of style.matchAll(/url\((['"]?)([^'")]+)\1\)|([^\s,]+\.(?:jpe?g|png|webp|gif|avif))/gi)) {
        push(m[2] || m[3] || "");
      }
    }
    return out.slice(0, max);
  } catch {
    return [];
  }
}
