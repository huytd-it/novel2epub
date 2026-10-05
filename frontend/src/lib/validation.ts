// Mirror của `CONTENT_CHECKS` trong novel2epub/build_validation.py — chạy
// client-side để highlight live trong lúc đang sửa chương.
//
// Ba chỗ báo lỗi phải ra CÙNG một tập vấn đề: trang Chương (file này), API
// `validate_chapter_detailed` (highlight per-para) và trang Build
// (`check_content`, gộp số lượng theo chương). Sửa luật ở đây thì sửa luôn
// build_validation.py — thứ tự, mã lỗi, level và ngưỡng phải khớp.
// Regex giữ nguyên ý nghĩa, chỉ đổi flag cho JS (thêm g, u khi cần).

export type ValidationLevel = "error" | "warning" | "info";
export interface ValidationIssue {
  code: string;
  level: ValidationLevel;
  message: string;
  hint?: string;
  paraIndex: number;
  start: number;
  end: number;
  snippet: string;
  method?: ValidationMethod;
  reason?: string;
  location?: "text" | "title" | "chapter";
}

export interface ChapterValidation {
  issues: ValidationIssue[];
  summary: { error: number; warning: number; info: number; total: number };
  perPara: Map<number, ValidationIssue[]>;
}

// Patterns — giữ đồng bộ với build_validation.py
const RE_HASH_HEADING = /(?:^|\n)\s*#{1,6}\s+/gm;
const RE_CODE_FENCE = /```/g;
const RE_WEIRD_DOTS = /(?:\.{2,}|…{2,}|·{2,}|。{2,})/g;
// Lặp ! và ? là cách nhấn mạnh thường dùng trong hội thoại (!!!, ???).
const RE_REPEATED_PUNCT = /([;,:\-–—])\1+/g;
const RE_CONTROL = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;
const RE_REPLACEMENT = /�/g;
const RE_MOJIBAKE = /[ÃÂ][\x80-\xBF]{1,2}/g;
const RE_ZERO_WIDTH = /[\u200b\ufeff]/g;
// Link/URL còn sót: watermark, quảng cáo, "đọc tiếp tại …" của trang nguồn.
// Nhánh 1 bắt link có scheme/`www.`; nhánh 2 bắt tên miền trần
// (truyenfull.vn) với TLD phổ biến, chặn hai đầu bằng lớp ký tự Latin mở rộng
// để không cắn vào chữ tiếng Việt có dấu.
const RE_URL =
  /(?:https?:\/\/|www\.)[^\s<>"'()[\]]+|(?<![A-Za-zÀ-ỹ0-9@._-])[A-Za-zÀ-ỹ0-9-]+(?:\.[A-Za-zÀ-ỹ0-9-]+)*\.(?:com|net|org|vn|info|xyz|top|club|site|online|io|biz|tv)(?![A-Za-zÀ-ỹ0-9-])(?:\/[^\s<>"'()[\]]*)?/gi;
const RE_HAN = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{2EBEF}]/u;
// Cụm Hán liên tiếp — 1 issue cho cả cụm thay vì từng ký tự
const RE_HAN_CLUSTER = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{2EBEF}]+/gu;
const RE_DOUBLE_SPACE = /[ \t]{2,}/g;
const RE_SPACE_BEFORE_PUNCT = /(?<=[\p{L}\p{N}])[ \t]+[,.!?;:)]/gu;
const RE_TRAILING_SPACE = /[ \t]+(?=\r?$)/gm;
const RE_MISSING_SPACE_AFTER = /[,.!?;:][a-zA-ZÀ-ỹ]/g;
// Unicode-aware: \p{L} cho chữ có dấu, tránh false positive "nhánh như" -> "nh nh"
const RE_REPEATED_WORD = /(?<![\p{L}\p{N}_])(\p{L}+)\s+\1(?![\p{L}\p{N}_])/giu;

// Mẫu tiêu đề hợp lệ — mirror của toc.title_format_ok
const RE_TITLE_FORMAT = /^Chương\s+\d+(?:[.\-]\d+)?(?:\s*[:：.\-–—]\s*\S.*|\s+\S.*)?$/i;

interface ContentCheck {
  code: string;
  level: ValidationLevel;
  pattern: RegExp;
  /** Message ngắn hiển thị ở từng vị trí highlight. */
  label: string;
  hint?: string;
  /** Số match tối thiểu TRONG MỘT ĐOẠN mới coi là lỗi. */
  minHits?: number;
  /** Các match đúng chuẩn, bỏ qua ("..." và "…" là dấu lửng hợp lệ). */
  ignore?: string[];
}

export const CONTENT_CHECKS: ContentCheck[] = [
  { code: "html_entity", level: "warning", pattern: /<\/?[A-Za-z][^<>\n]*>|&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);/g, label: "HTML/entity còn sót", hint: "Bóc thẻ, giữ nội dung hiển thị" },
  { code: "abbreviation", level: "info", pattern: /\b(?:v\.v\.?|v\.d\.?|ThS|PGS|TS|TP|UBND|CPU|AI)\b|(?<![a-zA-ZÀ-ỹ])(?:[A-Z]{2,6}|[A-Za-z](?:\.[A-Za-z])+(?:\.)?)(?![a-zA-ZÀ-ỹ])/g, label: "Từ viết tắt", hint: "Chỉ đánh dấu; có thể hợp lệ" },
  { code: "spelling", level: "warning", pattern: /[a-zA-ZÀ-ỹ]+(?:\.[a-zA-ZÀ-ỹ]+)*/g, label: "Từ nghi vấn chính tả", hint: "Heuristic; kiểm tra toàn từ theo ngữ cảnh" },
  { code: "effect_sound", level: "info", pattern: /(?<![\p{L}\p{N}_])(?:ầm|rầm|bùm|bốp|rẹt|leng keng|ting|đùng|soạt|mỉm cười|thở dài)(?![\p{L}\p{N}_])/giu, label: "Nhãn hiệu ứng/âm thanh", hint: "Chỉ đánh dấu, không mặc định là rác" },
  { code: "hash_heading", level: "warning", pattern: RE_HASH_HEADING, label: "Dòng bắt đầu bằng ##", hint: "Tiêu đề không nên có ##" },
  { code: "code_fence", level: "warning", pattern: RE_CODE_FENCE, label: "Chứa ```", hint: "Bỏ dấu ```; giữ nguyên văn bản bên trong" },
  { code: "weird_dots", level: "warning", pattern: RE_WEIRD_DOTS, label: "Dấu chấm lạ", hint: "Chuẩn hóa về … hoặc ...", ignore: ["...", "…"] },
  { code: "repeated_punct", level: "warning", pattern: RE_REPEATED_PUNCT, label: "Dấu câu lặp", hint: "Gộp về 1 dấu" },
  { code: "control_char", level: "error", pattern: RE_CONTROL, label: "Ký tự điều khiển", hint: "Có thể do copy từ web; xóa ký tự \\x00-\\x1F" },
  { code: "replacement_char", level: "error", pattern: RE_REPLACEMENT, label: "Ký tự �", hint: "Crawl sai encoding; kiểm tra source preset rồi crawl lại" },
  { code: "mojibake", level: "warning", pattern: RE_MOJIBAKE, label: "Mojibake", hint: "Có thể double-decode UTF-8; kiểm tra source encoding" },
  { code: "zero_width", level: "warning", pattern: RE_ZERO_WIDTH, label: "Zero-width", hint: "Vô hình nhưng làm sai tìm kiếm; nên xóa" },
  { code: "url", level: "warning", pattern: RE_URL, label: "Link/URL còn sót", hint: "Watermark hoặc quảng cáo của trang nguồn — xóa hoặc thêm vào strip_patterns" },
  { code: "han_remaining", level: "warning", pattern: RE_HAN_CLUSTER, label: "Chữ Hán còn sót", hint: "Dùng 'Dọn chữ Hán' hoặc dịch lại" },
  { code: "double_space", level: "info", pattern: RE_DOUBLE_SPACE, label: "Double-space", hint: "Thừa khoảng trắng" },
  { code: "space_before_punct", level: "info", pattern: RE_SPACE_BEFORE_PUNCT, label: "Thừa space trước dấu câu", hint: "Ví dụ 'xin chào ,' → 'xin chào,'" },
  { code: "trailing_space", level: "info", pattern: RE_TRAILING_SPACE, label: "Thừa space cuối dòng", hint: "Không ảnh hưởng EPUB nhưng nên dọn" },
  { code: "missing_space_after", level: "info", pattern: RE_MISSING_SPACE_AFTER, label: "Thiếu space sau dấu câu", hint: "Ví dụ 'xin chào,bạn' → 'xin chào, bạn'" },
  { code: "repeated_word", level: "info", pattern: RE_REPEATED_WORD, label: "Từ lặp liên tiếp", hint: "Tiếng Việt có từ láy (từ từ, xa xa) — chỉ báo khi >3 chỗ trong cùng đoạn", minHits: 4 },
];

export type ValidationMethod = "algorithm" | "ai" | "manual" | "informational";
const algorithmCodes = new Set(["hash_heading", "code_fence", "weird_dots", "repeated_punct", "control_char", "zero_width", "double_space", "space_before_punct", "trailing_space", "missing_space_after", "html_entity"]);
const aiCodes = new Set(["han_remaining", "replacement_char", "mojibake", "repeated_word", "url", "spelling"]);
export function supportedMethod(code: string): ValidationMethod {
  return algorithmCodes.has(code) ? "algorithm" : aiCodes.has(code) ? "ai" : ["abbreviation", "effect_sound", "short", "skipped"].includes(code) ? "informational" : "manual";
}
export const METHOD_LABELS: Record<ValidationMethod, string> = { algorithm: "Thuật toán", ai: "AI cần duyệt", manual: "Kiểm tra tay", informational: "Chỉ đánh dấu" };
export const VALIDATION_CONTRACT = [
  ...CONTENT_CHECKS.map(c => ({ code: c.code, label: c.label, level: c.level, location: "text", method: supportedMethod(c.code), reason: c.hint })),
  ...Object.entries({ missing_title: "Thiếu tiêu đề", title_format: "Tiêu đề sai mẫu", empty_content: "Nội dung rỗng", symbol_only: "Nội dung không đọc được", identical_content: "Trùng nội dung", number_missing: "Thiếu số chương", number_duplicate: "Trùng số chương", number_descending: "Số chương giảm" }).map(([code, label]) => ({ code, label, level: ["missing_title", "empty_content"].includes(code) ? "error" : "warning", location: ["missing_title", "title_format"].includes(code) ? "title" : "chapter", method: "manual" as ValidationMethod, reason: "Kiểm tra tay; AI chỉ đề xuất khi có hướng dẫn chi tiết, không suy đoán nội dung thiếu." })),
  ...Object.entries({ not_ready: "Chưa sẵn sàng build", too_short: "Nội dung quá ngắn", short: "Nội dung ngắn", skipped: "Chương bị bỏ qua", duplicate: "Trùng URL/tiêu đề" }).map(([code, label]) => ({ code, label, level: code === "not_ready" ? "error" : ["short", "skipped"].includes(code) ? "info" : "warning", location: "chapter", method: supportedMethod(code), reason: "Cùng kiểm tra trước Build EPUB; kiểm tra nguồn, không tự khôi phục nội dung." })),
];
export function spellingSuspect(token: string): boolean {
  return token.length >= 3 && /([aeiou])\1{2,}|[qx][bcdfghjklmnpqrstvwxz]{2,}|[bcdfghjklmnpqrstvwxz]{4,}/i.test(token);
}
export function filterValidation(validation: ChapterValidation, codes: string[]): ChapterValidation {
  const issues = validation.issues.filter(i => !codes.length || codes.includes(i.code));
  return { issues, ...summarize(issues) };
}

/** Clone regex để mỗi lần quét có `lastIndex` riêng (pattern dùng flag g). */
function matchesOf(pattern: RegExp, text: string): RegExpMatchArray[] {
  return [...text.matchAll(new RegExp(pattern.source, pattern.flags))];
}

function spanOf(match: RegExpMatchArray): [number, number] {
  const start = match.index ?? 0;
  return [start, start + match[0].length];
}

export function titleFormatOk(title: string): boolean {
  const value = (title || "").trim();
  if (!value) return false;
  return RE_TITLE_FORMAT.test(value) && !RE_HAN.test(value);
}

export function validateTitle(title: string): ValidationIssue[] {
  if (!(title || "").trim()) {
    return [{ code: "missing_title", level: "error", message: "Thiếu tiêu đề", hint: "Dùng 'Chuẩn hóa TOC'", paraIndex: -1, start: 0, end: 0, snippet: "" }];
  }
  if (!titleFormatOk(title)) {
    return [{
      code: "title_format",
      level: "warning",
      message: `Tiêu đề sai mẫu: ${title.slice(0, 60)}`,
      hint: "Mẫu đúng: 'Chương N: Tên chương' và không còn chữ Hán",
      paraIndex: -1,
      start: 0,
      end: title.length,
      snippet: title.slice(0, 60),
    }];
  }
  return [];
}

export function validateChapterText(
  text: string,
  opts: { title?: string } = {},
): ChapterValidation {
  const issues: ValidationIssue[] = [];

  if (opts.title !== undefined) issues.push(...validateTitle(opts.title));

  if (!text || !text.trim()) {
    issues.push({ code: "empty_content", level: "error", message: "Nội dung rỗng", hint: "Crawl/dịch lại", paraIndex: -1, start: 0, end: 0, snippet: "" });
    return { issues, ...summarize(issues) };
  }

  // Tách theo đúng notes.split_paras — mỗi dòng non-empty là 1 para, nên
  // paraIndex khớp với `translated_paras` mà reader đang render.
  const paras = text.split("\n").filter((p) => p.trim());
  if (!/[\p{L}\p{N}]/u.test(text)) issues.push({ code: "symbol_only", level: "warning", message: "Nội dung không đọc được/chỉ ký hiệu", hint: "Kiểm tra tay, không suy đoán khôi phục", paraIndex: -1, start: 0, end: 0, snippet: "" });

  paras.forEach((para, paraIndex) => {
    const urlSpans = matchesOf(RE_URL, para).map(spanOf);
    const abbreviationSpans = matchesOf(CONTENT_CHECKS.find(c => c.code === "abbreviation")!.pattern, para).map(spanOf);
    for (const check of CONTENT_CHECKS) {
      let matches = matchesOf(check.pattern, para);
      if (check.code === "spelling") matches = matches.filter(m => spellingSuspect(m[0]));
      if (check.code === "abbreviation") matches = matches.filter(m => !/^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/.test(m[0]));
      if (check.code === "missing_space_after") matches = matches.filter(m => { const [s, e] = spanOf(m); return !abbreviationSpans.some(([a, b]) => a <= s && e <= b); });
      if (check.ignore) matches = matches.filter((m) => !check.ignore!.includes(m[0]));
      if (check.code !== "url") {
        // Dấu chấm/space bên trong link không phải lỗi chính tả — bản thân
        // cái link đã được báo bằng mã `url`.
        matches = matches.filter((m) => {
          const [start, end] = spanOf(m);
          return !urlSpans.some(([s, e]) => s <= start && end <= e);
        });
      }
      if (matches.length < (check.minHits ?? 1)) continue;
      for (const match of matches) {
        const [start, end] = spanOf(match);
        issues.push({
          code: check.code,
          level: check.level,
          message: check.label,
          hint: check.hint,
          paraIndex,
          start,
          end,
          snippet: para.slice(Math.max(0, start - 12), Math.min(para.length, end + 12)).trim(),
        });
      }
    }
  });

  return { issues, ...summarize(issues) };
}

function summarize(issues: ValidationIssue[]): Omit<ChapterValidation, "issues"> {
  const perPara = new Map<number, ValidationIssue[]>();
  for (const issue of issues) {
    issue.method = supportedMethod(issue.code);
    issue.reason = issue.hint ?? "";
    issue.location = ["missing_title", "title_format"].includes(issue.code) ? "title" : issue.paraIndex >= 0 ? "text" : "chapter";
    if (!perPara.has(issue.paraIndex)) perPara.set(issue.paraIndex, []);
    perPara.get(issue.paraIndex)!.push(issue);
  }
  return {
    perPara,
    summary: {
      error: issues.filter((i) => i.level === "error").length,
      warning: issues.filter((i) => i.level === "warning").length,
      info: issues.filter((i) => i.level === "info").length,
      total: issues.length,
    },
  };
}
