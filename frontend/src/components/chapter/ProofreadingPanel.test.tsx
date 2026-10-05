// @vitest-environment node
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProofreadingCodes, ProofreadingDiff, sameProofreadingDraft, type ProofreadingDraft } from "./ProofreadingPanel";
import type { ProofreadingCandidate } from "@/lib/chapter";

describe("proofreading incumbent UI", () => {
  it("draft/title/revision/publication view changes and changed-then-reverted drafts reject old results", () => {
    const base: ProofreadingDraft = { slug: "mock", index: 1, branch: "local_mt", revision: 2, generation: 10, editing: true, title: "Chương 1", text: "😀 中" };
    expect(sameProofreadingDraft(base, { ...base })).toBe(true);
    for (const change of [{ text: "changed" }, { title: "title changed" }, { branch: "ai" }, { revision: 3 }, { index: 2 }, { slug: "other" }, { editing: false }, { generation: 12 }]) expect(sameProofreadingDraft(base, { ...base, ...change })).toBe(false);
  });
  it("full chapter diff preserves non-BMP and final text beyond 2000 chars", () => {
    const before = "😀 中\n\n" + "Nội dung nguyên vẹn.\n".repeat(1000) + "DẤU CUỐI CHƯƠNG";
    const candidate: ProofreadingCandidate = { before, base: { index: 1, branch: "local_mt", revision: 1, hash: "hash", title: "Chương 1: Thử", text: before }, after: before.replace("中", "Trung"), title: "Chương 1: Thử", draft: false, draft_hash: "hash", diff: "", edits: [{ start: 2, end: 3, original: "中", replacement: "Trung" }] };
    const output = renderToStaticMarkup(<ProofreadingDiff candidate={candidate} before={before} />);
    expect(output).toContain("😀 ");
    expect(output).toContain("Trung</mark>");
    expect(output).toContain("中</mark>");
    expect(output.match(/DẤU CUỐI CHƯƠNG/g)).toHaveLength(2);
    expect(output.length).toBeGreaterThan(30000);
  });
  it("multiple selected codes have Vietnamese method labels and native keyboard inputs", () => {
    const output = renderToStaticMarkup(<ProofreadingCodes codes={["han_remaining", "double_space"]} onChange={() => {}} issues={[]} />);
    expect(output).toContain("2 loại đã chọn");
    expect(output.match(/checked=""/g)).toHaveLength(2);
    expect(output).toContain("AI cần duyệt");
    expect(output).toContain("Thuật toán");
    expect(output).toContain("Chỉ đánh dấu");
    expect(output).toContain("type=\"checkbox\"");
  });
  it("no codes indicates all but not selected for fixing", () => {
    const output = renderToStaticMarkup(<ProofreadingCodes codes={[]} onChange={() => {}} issues={[]} />);
    expect(output).toContain("Tất cả (chưa chọn để sửa)");
    expect(output).not.toContain("checked=\"\"");
  });
  it("book-level code selection does not claim uncomputed zero issue counts", () => {
    const output = renderToStaticMarkup(<ProofreadingCodes codes={[]} onChange={() => {}} />);
    expect(output).toContain("không lọc bảng chương");
    expect(output).not.toContain("Số lần trong chương đang mở");
    expect(output).not.toContain("(0)");
  });
});
