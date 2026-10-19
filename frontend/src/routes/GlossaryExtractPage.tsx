import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { Badge, type Tone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox, Select } from "@/components/ui/Field";
import { Loading } from "@/components/ui/Loading";
import { Page } from "@/app/Shell";
import { EmptyState } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";

interface Candidate {
  source: string;
  kind: "translit" | "cn_name" | "term";
  frequency: number;
  confidence: number;
  chapter_index: number;
  context: string;
  status: "new" | "glossary" | "pending";
}

interface ExtractResult {
  scanned_chapters: number;
  detected: number;
  queued: number;
  skipped_existing: number;
  candidates: Candidate[];
}

const KIND: Record<Candidate["kind"], { text: string; tone: Tone }> = {
  translit: { text: "Phiên âm", tone: "indigo" },
  cn_name: { text: "Tên Trung Quốc", tone: "neutral" },
  term: { text: "Thuật ngữ", tone: "gold" },
};

const STATUS: Record<Candidate["status"], { text: string; tone: Tone }> = {
  new: { text: "Chờ duyệt", tone: "gold" },
  pending: { text: "Đã ở hàng chờ", tone: "neutral" },
  glossary: { text: "Đã có glossary", tone: "celadon" },
};

/**
 * Thử nghiệm: dò tên riêng trong nội dung gốc (raw) của chương bằng heuristic
 * (họ Trung Quốc + bảng chữ phiên âm), không gọi AI. Ứng viên chỉ hiện ở đây
 * dưới dạng chờ duyệt; bấm duyệt mới đưa vào hàng chờ của trang Glossary.
 */
export function GlossaryExtractor({
  slug,
  chapterIndexes,
  includeTerms = false,
}: {
  slug: string;
  /** Chương đang chọn; rỗng = quét toàn bộ truyện. */
  chapterIndexes: number[];
  includeTerms?: boolean;
}) {
  const toast = useToast();
  const client = useQueryClient();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [terms, setTerms] = useState(includeTerms);
  const [engine, setEngine] = useState("localmt");

  const request = (extra: Record<string, unknown>) =>
    api.post<ExtractResult>(`/api/ebooks/${slug}/glossary/proper-names/extract`, {
      body: {
        chapter_indexes: chapterIndexes.length > 0 ? chapterIndexes : null,
        translate: engine !== "none",
        translate_engine: engine === "localmt" ? "localmt" : "ebook",
        include_terms: terms,
        ...extra,
      },
    });
  const scan = useMutation({ mutationFn: () => request({ dry_run: true }) });
  const queue = useMutation({
    mutationFn: (sources: string[]) => request({ sources }),
    onSuccess: (result, sources) => {
      toast(`Đã đưa ${num(result.queued)} tên vào hàng chờ Glossary.`);
      setDismissed((prev) => new Set([...prev, ...sources]));
      setChecked(new Set());
      client.invalidateQueries({ queryKey: ["glossary-pending", slug] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  useEffect(() => {
    setChecked(new Set());
    setDismissed(new Set());
    scan.reset();
    scan.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- engine chỉ dùng khi đưa vào hàng chờ
  }, [terms]);

  const rows = useMemo(
    () => (scan.data?.candidates ?? []).filter((c) => !dismissed.has(c.source)),
    [scan.data, dismissed],
  );
  const fresh = rows.filter((c) => c.status === "new");
  const allChecked = fresh.length > 0 && fresh.every((c) => checked.has(c.source));
  const toggle = (source: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[13px]">
          Bản dịch khi đưa vào hàng chờ
          <Select aria-label="Engine dịch ứng viên" value={engine} disabled={queue.isPending}
            onChange={(event) => setEngine(event.target.value)}>
            <option value="localmt">Dịch thô Local MT (không gọi AI)</option>
            <option value="ebook">Engine mặc định của ebook</option>
            <option value="none">Giữ nguyên chữ Hán</option>
          </Select>
        </label>
          <Button
            disabled={checked.size === 0 || queue.isPending}
            onClick={() => {
              setDismissed((prev) => new Set([...prev, ...checked]));
              setChecked(new Set());
            }}
          >
            Bỏ qua {checked.size > 0 ? num(checked.size) : ""}
          </Button>
          <Button
            variant="primary"
            loading={queue.isPending}
            disabled={checked.size === 0 || scan.isPending}
            onClick={() => queue.mutate([...checked])}
          >
            {engine === "localmt" ? "Dịch thô & đưa" : "Đưa"} {checked.size > 0 ? num(checked.size) : ""} vào hàng chờ Glossary
          </Button>
      </div>
      <label className="mb-3 flex items-center gap-2 text-[13px]">
        <Checkbox checked={terms} disabled={queue.isPending} onChange={(event) => setTerms(event.target.checked)} />
        Bao gồm thuật ngữ lặp
      </label>
      <p className="mb-3 text-[13px] opacity-60">
        Dò tên người trong nội dung gốc của{" "}
        {chapterIndexes.length > 0 ? `${num(chapterIndexes.length)} chương đang chọn` : "toàn bộ truyện"} bằng
        heuristic (họ Trung Quốc, bảng chữ phiên âm), không gọi AI nên có thể sót hoặc lẫn từ thường. Tên được
        duyệt sẽ vào tab Chờ duyệt của{" "}
        <Link className="link" to={`/ebooks/${slug}/glossary`}>
          Glossary
        </Link>{" "}
        theo lựa chọn dịch phía trên. Local MT chỉ tạo bản dịch thô để duyệt lại;
        nếu engine không khả dụng thì giữ chữ Hán. Không tự ghi glossary chính.
      </p>

      {scan.isPending ? (
        <Loading />
      ) : scan.isError ? (
        <EmptyState
          title="Không trích được tên riêng"
          hint={scan.error instanceof Error ? scan.error.message : String(scan.error)}
          action={<Button onClick={() => scan.mutate()}>Thử lại</Button>}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="Không tìm thấy ứng viên"
          hint="Cần chương đã có nội dung gốc; ngưỡng mặc định là 3 lần (hoặc theo cấu hình ebook)."
        />
      ) : (
        <>
          <div data-numeric className="mb-2 text-[13px] opacity-60">
            {num(scan.data?.scanned_chapters ?? 0)} chương đã quét · {num(fresh.length)} tên chờ duyệt ·{" "}
            {num(rows.length - fresh.length)} tên đã có
          </div>
          <div className="overflow-x-auto rounded-box border border-base-300">
            <table className="w-full border-collapse text-left text-[13px]">
              <thead className="sticky top-0 bg-base-200">
                <tr className="border-b border-base-300">
                  <th className="w-8 px-2 py-1.5">
                    <Checkbox
                      checked={allChecked}
                      title="Chọn tất cả tên chờ duyệt"
                      onClick={() => setChecked(allChecked ? new Set() : new Set(fresh.map((c) => c.source)))}
                      onChange={() => {}}
                    />
                  </th>
                  {["Hán", "Loại", "Số lần", "Ngữ cảnh", "Trạng thái"].map((label) => (
                    <th
                      key={label}
                      className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] whitespace-nowrap uppercase opacity-40"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const isNew = c.status === "new";
                  return (
                    <tr
                      key={c.source}
                      className={
                        isNew
                          ? "border-b border-base-300 bg-warning/10 transition-colors last:border-b-0 hover:bg-primary/10"
                          : "border-b border-base-300 opacity-50 last:border-b-0"
                      }
                    >
                      <td className="px-2 py-1">
                        {isNew ? (
                          <Checkbox
                            checked={checked.has(c.source)}
                            onClick={() => toggle(c.source)}
                            onChange={() => {}}
                          />
                        ) : null}
                      </td>
                      <td className="px-2 py-1 font-medium whitespace-nowrap">{c.source}</td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <Badge tone={KIND[c.kind].tone}>{KIND[c.kind].text}</Badge>
                      </td>
                      <td data-numeric className="px-2 py-1 whitespace-nowrap">
                        {num(c.frequency)}
                      </td>
                      <td className="px-2 py-1 opacity-70">{c.context || "—"}</td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <Badge tone={STATUS[c.status].tone}>{STATUS[c.status].text}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

export function GlossaryExtractPage() {
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const chapters = [...new Set((params.get("chapters") ?? "").split(",").filter(Boolean)
    .map(Number).filter((value) => Number.isSafeInteger(value) && value > 0))];
  const terms = params.get("terms") !== "false";
  return <Page title={terms ? "Trích glossary" : "Trích tên riêng"}
    hint="Quét raw, chọn ứng viên và đưa bản dịch thô vào hàng chờ duyệt."
    actions={<><Link className="link" to={`/ebooks/${slug}`}>Về trang Chương</Link>
      <Link className="link" to={`/ebooks/${slug}/glossary`}>Mở Glossary</Link></>}>
    <GlossaryExtractor key={`${slug}:${terms}:${chapters.join(",")}`} slug={slug} chapterIndexes={chapters} includeTerms={terms} />
  </Page>;
}
