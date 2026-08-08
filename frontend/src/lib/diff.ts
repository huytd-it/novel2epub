/**
 * Diff theo TỪ giữa hai đoạn văn — dùng để tô chỗ bản biên tập lệch khỏi bản
 * dịch máy.
 *
 * Cắt theo từ chứ không theo ký tự: tiếng Việt có dấu, diff mức ký tự sẽ vỡ
 * vụn thành hàng chục mảnh trong cùng một chữ và đọc không ra gì. Cắt giữ luôn
 * cả khoảng trắng vào token để ghép lại không mất định dạng.
 */

export type DiffOp = "same" | "add" | "del";

export interface DiffPart {
  op: DiffOp;
  text: string;
}

/** Tách thành token "từ + khoảng trắng theo sau" để nối lại là ra chuỗi gốc. */
function tokenize(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

/** So sánh bỏ qua khoảng trắng thừa — xuống dòng khác nhau không tính là sửa. */
function normalize(token: string): string {
  return token.trim();
}

/**
 * Độ dài dãy con chung dài nhất, dạng ma trận cuộn 2 hàng.
 *
 * Đủ cho một đoạn văn (vài trăm từ). Không dùng cho cả chương: O(n·m) bộ nhớ
 * theo số từ sẽ phình rất nhanh — gọi hàm này theo từng đoạn đã ghép cặp.
 */
function lcsTable(a: string[], b: string[]): Uint32Array[] {
  const rows: Uint32Array[] = [];
  let prev = new Uint32Array(b.length + 1);
  rows.push(prev);
  for (let i = 0; i < a.length; i++) {
    const cur = new Uint32Array(b.length + 1);
    for (let j = 0; j < b.length; j++) {
      cur[j + 1] =
        normalize(a[i]) === normalize(b[j])
          ? prev[j] + 1
          : Math.max(cur[j], prev[j + 1]);
    }
    rows.push(cur);
    prev = cur;
  }
  return rows;
}

/**
 * Diff `before` → `after`. `del` là phần chỉ có ở `before`, `add` chỉ có ở
 * `after`. Hai chuỗi giống hệt trả về đúng một phần `same`.
 */
export function diffWords(before: string, after: string): DiffPart[] {
  if (before === after) return before ? [{ op: "same", text: before }] : [];
  const a = tokenize(before);
  const b = tokenize(after);
  if (a.length === 0) return b.length ? [{ op: "add", text: b.join("") }] : [];
  if (b.length === 0) return [{ op: "del", text: a.join("") }];

  const table = lcsTable(a, b);

  // Truy vết ngược từ (len(a), len(b)) rồi đảo lại — đi xuôi sẽ phải đoán
  // nhánh nào dẫn tới LCS tối ưu.
  const parts: DiffPart[] = [];
  let i = a.length;
  let j = b.length;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && normalize(a[i - 1]) === normalize(b[j - 1])) {
      // Giữ token của bản SAU: chỉ khác khoảng trắng thì hiển thị theo bản mới.
      parts.push({ op: "same", text: b[j - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || table[i][j - 1] >= table[i - 1][j])) {
      parts.push({ op: "add", text: b[j - 1] });
      j--;
    } else {
      parts.push({ op: "del", text: a[i - 1] });
      i--;
    }
  }
  parts.reverse();

  // Gộp các phần liền nhau cùng loại: nếu không, mỗi từ là một <span> và DOM
  // phình ra vô ích.
  const merged: DiffPart[] = [];
  for (const part of parts) {
    const last = merged[merged.length - 1];
    if (last && last.op === part.op) last.text += part.text;
    else merged.push({ ...part });
  }
  return merged;
}

/** Có khác biệt thật không (bỏ qua chênh lệch khoảng trắng). */
export function hasRealDiff(before: string, after: string): boolean {
  if (before === after) return false;
  return tokenize(before).map(normalize).join(" ") !== tokenize(after).map(normalize).join(" ");
}
