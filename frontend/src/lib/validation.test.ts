import { describe, expect, it } from "vitest";
import cases from "../../../tests/fixtures/proofreading_validation.json";
import { validateChapterText, filterValidation, supportedMethod } from "./validation";

const codesOf = (text: string, title = "Chương 1: Test") =>
  new Set(validateChapterText(text, { title }).issues.filter((i) => i.paraIndex >= 0).map((i) => i.code));

describe("validateChapterText (existing regression tests)", () => {
  it("bỏ qua ??? và !!! nhưng vẫn báo dấu câu lặp kiểu ,, ;; ::", () => {
    expect(codesOf("Thật sao??? Không thể nào!!!")).not.toContain("repeated_punct");
    expect(codesOf("Sai,, rồi; ; ổn:: không--")).toContain("repeated_punct");
  });
  it("bắt link có scheme, www. và tên miền trần", () => {
    const issues = validateChapterText("Đọc tiếp tại https://truyenfull.vn/abc nhé.\nGhé thăm truyenfull.vn hoặc www.metruyenchu.com.", { title: "Chương 1: Test" }).issues.filter(i => i.code === "url");
    expect(issues).toHaveLength(3);
    expect(issues[0].level).toBe("warning");
  });
  it("không nhầm văn xuôi tiếng Việt là link", () => {
    expect(codesOf("Hắn nói: “Chuyện này không đơn giản.” Rồi lặng lẽ bỏ đi.\nTừ từ thôi, cô ấy vẫn còn ở đó.")).not.toContain("url");
  });
  it("không báo lỗi chính tả cho dấu chấm nằm trong link", () => {
    expect(codesOf("Nguồn: https://truyenfull.vn/chuong-1.html")).toEqual(new Set(["url"]));
  });
  it("chỉ báo từ lặp khi bất thường trong cùng một đoạn", () => {
    expect(codesOf("Từ từ thôi, xa xa có bóng người, nhè nhẹ gió thổi qua.")).not.toContain("repeated_word");
    expect(codesOf("rồi rồi ạ, thôi thôi nào, đi đi mà, nhanh nhanh lên nhé.")).toContain("repeated_word");
  });
  it("gom chữ Hán liên tiếp thành một vấn đề", () => {
    const han = validateChapterText("中国語 xuất hiện ở đây.", { title: "Chương 1: Test" }).issues.filter(i => i.code === "han_remaining");
    expect(han).toHaveLength(1);
    expect(han[0].level).toBe("warning");
  });
  it("báo tiêu đề sai mẫu và nội dung rỗng ở mức chương", () => {
    const result = validateChapterText("", { title: "Chuong 1" });
    expect(result.issues.map(i => i.code)).toContain("title_format");
    expect(result.issues.map(i => i.code)).toContain("empty_content");
    expect(result.summary.error).toBe(1);
  });
});

describe("shared Python/JS validation fixtures", () => {
  for (const fixture of cases) it(fixture.name, () => {
    const report = validateChapterText(fixture.text, { title: fixture.title });
    expect([...new Set(report.issues.map(i => i.code))].sort()).toEqual([...fixture.codes].sort());
    if (fixture.spans) expect(report.issues.map(i => [i.paraIndex, i.start, i.end])).toEqual(fixture.spans);
  });
  it("multi-code controls both list and highlight; none shows all", () => {
    const report = validateChapterText("😀 中  tiếp", { title: "Chương 1: Thử" });
    const filtered = filterValidation(report, ["han_remaining"]);
    expect(filtered.issues.map(i => i.code)).toEqual(["han_remaining"]);
    expect(filtered.perPara.get(0)?.[0].start).toBe(3);
    expect(filterValidation(report, []).summary.total).toBe(report.summary.total);
    expect(supportedMethod("han_remaining")).toBe("ai");
    expect(supportedMethod("double_space")).toBe("algorithm");
    expect(supportedMethod("effect_sound")).toBe("informational");
  });
});
