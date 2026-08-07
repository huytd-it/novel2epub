import type { ChapterState } from "@/components/ChapterStrip";

const CODES: Record<string, ChapterState> = {
  n: "none",
  r: "raw",
  m: "mt",
  e: "edited",
  s: "skip",
  x: "error",
};

/** Giải nén chuỗi run-length từ `/api/ui/library` ('e120,m40,n1500'). */
export function decodeStrip(encoded: string): ChapterState[] {
  if (!encoded) return [];
  const out: ChapterState[] = [];
  for (const part of encoded.split(",")) {
    const state = CODES[part[0]];
    const count = Number.parseInt(part.slice(1), 10);
    if (!state || !Number.isFinite(count)) continue;
    for (let i = 0; i < count; i++) out.push(state);
  }
  return out;
}

export function stripCounts(counts: Record<string, number>): Partial<Record<ChapterState, number>> {
  const out: Partial<Record<ChapterState, number>> = {};
  for (const [code, value] of Object.entries(counts)) {
    const state = CODES[code];
    if (state && value) out[state] = value;
  }
  return out;
}
