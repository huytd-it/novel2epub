// Mirror của novel2epub/build_validation.py — chạy client-side để highlight live
// Regex giữ nguyên ý nghĩa, chỉ đổi flag cho JS (thêm g, u khi cần)

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
}

export interface ChapterValidation {
  issues: ValidationIssue[];
  summary: { error: number; warning: number; info: number; total: number };
  perPara: Map<number, ValidationIssue[]>;
}

// Patterns — giữ đồng bộ với build_validation.py
const RE_HASH_HEADING = /(?:^|\n)\s*#{1,6}\s+/gm;
const RE_CODE_FENCE = /```/g;
const RE_WEIRD_DOTS = /(?:\.{2,}|…+|·{2,}|。{2,})/g;
const RE_REPEATED_PUNCT = /([!?;,:\-–—])\1+/g;
const RE_CONTROL = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;
const RE_REPLACEMENT = /\uFFFD/g;
const RE_MOJIBAKE = /[ÃÂ][\x80-\xBF]{1,2}/g;
const RE_ZERO_WIDTH = /[\u200B\u200C\u200D\uFEFF]/g;
const RE_HAN = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/gu;
const RE_DOUBLE_SPACE = /  +/g;
const RE_SPACE_BEFORE_PUNCT = /\s+[,.!?;:)]/g;
const RE_TRAILING_SPACE = / +$/gm;

// Cần reset lastIndex trước mỗi lần matchAll trên chuỗi lặp lại
function collectMatches(
  pattern: RegExp,
  text: string,
  code: string,
  level: ValidationLevel,
  message: string,
  hint: string,
  paraIndex: number,
  out: ValidationIssue[],
) {
  // pattern có flag g, phải clone để không chia sẻ lastIndex
  const re = new RegExp(pattern.source, pattern.flags);
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    // Bỏ qua "..." chuẩn và "…" đơn — chỉ highlight weird
    if (code === "weird_dots" && (m[0] === "..." || m[0] === "…")) continue;
    out.push({
      code,
      level,
      message,
      hint,
      paraIndex,
      start,
      end,
      snippet: m[0].slice(0, 30),
    });
  }
}

// Special handling cho han: highlight từng cụm han liên tiếp
function collectHan(text: string, paraIndex: number, out: ValidationIssue[]) {
  // cụm han liên tiếp — dùng cluster thay vì từng ký tự để tránh duplicate
  const clusterRe = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+/gu;
  for (const m of text.matchAll(clusterRe)) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    out.push({
      code: "han_remaining",
      level: "warning",
      message: "Chữ Hán còn sót",
      hint: "Dùng 'Dọn chữ Hán'",
      paraIndex,
      start,
      end,
      snippet: text.slice(start, Math.min(end, start + 10)),
    });
  }
}

function collectRepeatedWord(text: string, paraIndex: number, out: ValidationIssue[]) {
  // Unicode-aware: \p{L} cho chữ có dấu, tránh false positive "nhánh như" -> "nh nh"
  // Chỉ báo khi lặp >3 lần trong cùng đoạn để tránh flag từ láy hợp lệ như "từ từ"
  const re = /(?<![\p{L}\p{N}_])(\p{L}+)\s+\1(?![\p{L}\p{N}_])/giu;
  const matches = [...text.matchAll(re)];
  if (matches.length <= 3) return;
  for (const m of matches) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    out.push({
      code: "repeated_word",
      level: "info",
      message: "Từ lặp liên tiếp",
      paraIndex,
      start,
      end,
      snippet: m[0],
    });
  }
}

export function validateChapterText(
  text: string,
  opts: { title?: string } = {},
): ChapterValidation {
  const issues: ValidationIssue[] = [];
  if (!text || !text.trim()) {
    if (text === undefined || text === null) return { issues: [], summary: { error: 0, warning: 0, info: 0, total: 0 }, perPara: new Map() };
    // empty check done by caller; still return
  }

  // Tách theo đúng notes.split_paras — mỗi dòng non-empty là 1 para
  const paras = text.split("\n").filter((p) => p.trim());
  // Nhưng để giữ mapping đúng paraIndex, ta cần map paraIndex → text
  // Ở ChapterPage, paragraphs đã là split_paras rồi; tuy nhiên ở đây ta tự tách
  // Để đồng bộ, ta nhận text gốc và tự tách; paraIndex sẽ khớp với data.translated_paras

  paras.forEach((para, paraIndex) => {
    collectMatches(RE_HASH_HEADING, para, "hash_heading", "warning", "Dòng bắt đầu bằng ##", "Tiêu đề không nên có ##", paraIndex, issues);
    collectMatches(RE_CODE_FENCE, para, "code_fence", "warning", "Chứa ```", "Xóa khối code", paraIndex, issues);
    collectMatches(RE_WEIRD_DOTS, para, "weird_dots", "warning", "Dấu chấm lạ", "Chuẩn hóa về …", paraIndex, issues);
    collectMatches(RE_REPEATED_PUNCT, para, "repeated_punct", "warning", "Dấu câu lặp", "Gộp về 1 dấu", paraIndex, issues);
    collectMatches(RE_CONTROL, para, "control_char", "error", "Ký tự điều khiển", "", paraIndex, issues);
    collectMatches(RE_REPLACEMENT, para, "replacement_char", "error", "Ký tự �", "Lỗi mã hóa", paraIndex, issues);
    collectMatches(RE_MOJIBAKE, para, "mojibake", "warning", "Mojibake", "", paraIndex, issues);
    collectMatches(RE_ZERO_WIDTH, para, "zero_width", "warning", "Zero-width", "", paraIndex, issues);
    collectHan(para, paraIndex, issues);
    collectMatches(RE_DOUBLE_SPACE, para, "double_space", "info", "Double-space", "", paraIndex, issues);
    collectMatches(RE_SPACE_BEFORE_PUNCT, para, "space_before_punct", "info", "Thừa space trước dấu câu", "", paraIndex, issues);
    collectMatches(RE_TRAILING_SPACE, para, "trailing_space", "info", "Thừa space cuối dòng", "", paraIndex, issues);
    collectRepeatedWord(para, paraIndex, issues);
    // missing_space_after: pattern [,.!?;:][^\s\d\W] — cần check per para
    const reMissing = /[,.!?;:][^\s\d\W]/g;
    collectMatches(reMissing, para, "missing_space_after", "info", "Thiếu space sau dấu câu", "", paraIndex, issues);
  });

  // title check (nếu có)
  if (opts.title !== undefined) {
    const title = opts.title || "";
    if (!title.trim()) {
      issues.push({ code: "missing_title", level: "error", message: "Thiếu tiêu đề", paraIndex: -1, start: 0, end: 0, snippet: "" });
    }
  }

  const perPara = new Map<number, ValidationIssue[]>();
  for (const iss of issues) {
    if (!perPara.has(iss.paraIndex)) perPara.set(iss.paraIndex, []);
    perPara.get(iss.paraIndex)!.push(iss);
  }

  const summary = {
    error: issues.filter((i) => i.level === "error").length,
    warning: issues.filter((i) => i.level === "warning").length,
    info: issues.filter((i) => i.level === "info").length,
    total: issues.length,
  };

  return { issues, summary, perPara };
}

export function validateTitle(title: string): ValidationIssue[] {
  const out: ValidationIssue[] = [];
  if (!title || !title.trim()) {
    out.push({ code: "missing_title", level: "error", message: "Thiếu tiêu đề", paraIndex: -1, start: 0, end: 0, snippet: "" });
  } else {
    // title_format_ok mirror: phải là "Chương N..." và không có Hán
    const ok = /^Chương\s+\d+(?:[.\-]\d+)?(?:\s*[:：.\-–—]\s*\S.*|\s+\S.*)?$/i.test(title.trim()) && !RE_HAN.test(title);
    RE_HAN.lastIndex = 0;
    if (!ok) {
      out.push({ code: "title_format", level: "warning", message: `Tiêu đề sai mẫu: ${title.slice(0, 60)}`, paraIndex: -1, start: 0, end: title.length, snippet: title });
    }
    if (RE_HAN.test(title)) {
      RE_HAN.lastIndex = 0;
      out.push({ code: "han_in_title", level: "warning", message: "Tiêu đề còn chữ Hán", paraIndex: -1, start: 0, end: 0, snippet: "" });
    }
  }
  return out;
}
