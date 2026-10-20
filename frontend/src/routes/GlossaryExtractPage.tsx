import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { Badge, type Tone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox, Input, Select } from "@/components/ui/Field";
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

interface Translation {
  source: string;
  target: string;
  context_target: string;
  engine: "localmt" | "openai";
  error: string;
}

interface PreviewJob {
  id: string;
  state: "pending" | "running" | "done" | "failed" | "cancelled";
  outcome?: { entries: Translation[] };
  error?: string;
  log: string[];
}

function readPreviewJob(key: string): { id: string; terms: boolean } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return value && typeof value.id === "string" && typeof value.terms === "boolean" ? value : null;
  } catch { return null; }
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
  const [translations, setTranslations] = useState<Record<string, Translation>>({});
  const jobKey = `glossary-extract-preview:${slug}:${chapterIndexes.join(",")}:${includeTerms}`;
  const [previewJob, setPreviewJob] = useState(() => readPreviewJob(jobKey));
  const appliedJob = useRef("");
  const activeJob = previewJob?.terms === terms ? previewJob : null;
  const jobStatus = useQuery({
    queryKey: ["glossary-extract-preview", slug, activeJob?.id],
    enabled: Boolean(activeJob),
    queryFn: () => api.get<PreviewJob>(`/api/ebooks/${slug}/glossary/proper-names/translate/${activeJob!.id}`),
    retry: false,
    refetchInterval: (query) => query.state.status === "error" || (query.state.data &&
      !["pending", "running"].includes(query.state.data.state)) ? false : 1500,
  });
  const jobActive = Boolean(activeJob &&
    (!jobStatus.data || ["pending", "running"].includes(jobStatus.data.state)));

  const request = (extra: Record<string, unknown>) =>
    api.post<ExtractResult>(`/api/ebooks/${slug}/glossary/proper-names/extract`, {
      body: {
        chapter_indexes: chapterIndexes.length > 0 ? chapterIndexes : null,
        translate: false,
        include_terms: terms,
        ...extra,
      },
    });
  const scan = useMutation({ mutationFn: () => request({ dry_run: true }) });
  const queue = useMutation({
    mutationFn: (sources: string[]) => request({ sources,
      targets: engine === "none" ? {} : Object.fromEntries(sources.filter((source) => translations[source]?.target.trim())
        .map((source) => [source, translations[source].target.trim()])),
    }),
    onSuccess: (result, sources) => {
      toast(`Đã đưa ${num(result.queued)} tên vào hàng chờ Glossary.`);
      setDismissed((prev) => new Set([...prev, ...sources]));
      setChecked(new Set());
      client.invalidateQueries({ queryKey: ["glossary-pending", slug] });
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const translate = useMutation({
    mutationFn: async () => {
      const entries = (scan.data?.candidates ?? []).filter((row) => checked.has(row.source))
        .map(({ source, context }) => ({ source, context }));
      return api.post<{ job_id: string; category: string }>(`/api/ebooks/${slug}/glossary/proper-names/translate`, {
        body: { entries, engine },
      });
    },
    onSuccess: (result) => {
      const record = { id: result.job_id, terms };
      setPreviewJob(record);
      try { sessionStorage.setItem(jobKey, JSON.stringify(record)); } catch { /* storage unavailable */ }
      client.invalidateQueries({ queryKey: ["queue"] });
      toast("Đã đưa lượt dịch vào Job Queue.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/api/queue/${activeJob!.id}/cancel`),
    onSuccess: () => { jobStatus.refetch(); client.invalidateQueries({ queryKey: ["queue"] }); },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });
  const busy = queue.isPending || translate.isPending || jobActive;

  useEffect(() => {
    setChecked(new Set());
    setDismissed(new Set());
    setTranslations({});
    appliedJob.current = "";
    scan.reset();
    scan.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- engine chỉ dùng khi đưa vào hàng chờ
  }, [terms]);

  useEffect(() => {
    const result = jobStatus.data;
    if (!activeJob || result?.id !== activeJob.id || result.state !== "done" || appliedJob.current === result.id) return;
    appliedJob.current = result.id;
    setTranslations((previous) => ({ ...previous,
      ...Object.fromEntries((result.outcome?.entries ?? []).map((row) => [row.source, row])),
    }));
  }, [jobStatus.data, activeJob]);

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
        <label className="flex flex-wrap items-center gap-2 text-[13px]">
          Engine dịch xem trước
          <Select aria-label="Engine dịch ứng viên" value={engine} disabled={busy}
            onChange={(event) => setEngine(event.target.value)}>
            <option value="localmt">Dịch thô Local MT (không gọi AI)</option>
            <option value="openai">LLM (DEFAULT_PROMPT, nhiều dòng mỗi lượt)</option>
            <option value="none">Giữ nguyên chữ Hán</option>
          </Select>
        </label>
          <Button loading={translate.isPending || jobActive} disabled={busy || checked.size === 0 || scan.isPending || engine === "none"}
            onClick={() => translate.mutate()}>
            Dịch {checked.size > 0 ? num(checked.size) : ""} dòng đã chọn
          </Button>
          <Button
            disabled={checked.size === 0 || busy}
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
            disabled={checked.size === 0 || busy || scan.isPending}
            onClick={() => queue.mutate([...checked])}
          >
            Đưa {checked.size > 0 ? num(checked.size) : ""} vào hàng chờ Glossary
          </Button>
      </div>
      {activeJob && <div className="mb-3 flex flex-wrap items-center gap-3 text-[13px]">
        <span role="status">Job dịch: {jobStatus.isError ? "Không lấy được trạng thái" :
          ({ pending: "Đang chờ", running: "Đang dịch", done: "Hoàn tất", failed: "Thất bại", cancelled: "Đã hủy" }[jobStatus.data?.state ?? "pending"])}</span>
        <Link className="link" to="/queue">Mở Job Queue</Link>
        {jobActive && <Button size="sm" loading={cancel.isPending} onClick={() => cancel.mutate()}>Hủy job dịch</Button>}
        {jobStatus.isError && <Button size="sm" onClick={() => jobStatus.refetch()}>Kiểm tra lại</Button>}
        {jobStatus.isError && <Button size="sm" onClick={() => {
          setPreviewJob(null);
          try { sessionStorage.removeItem(jobKey); } catch { /* storage unavailable */ }
        }}>Bỏ theo dõi (không hủy job)</Button>}
        {jobStatus.data?.log?.length ? <span className="opacity-70">{jobStatus.data.log[jobStatus.data.log.length - 1]}</span> : null}
        {jobStatus.data?.error && <span role="alert" className="text-error">{jobStatus.data.error}</span>}
      </div>}
      <label className="mb-3 flex items-center gap-2 text-[13px]">
        <Checkbox aria-label="Bao gồm thuật ngữ lặp" checked={terms} disabled={busy} onChange={(event) => setTerms(event.target.checked)} />
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
        sau khi bạn bấm đưa vào hàng chờ. Bấm Dịch để xem bản dịch cả Hán và ngữ cảnh trước;
        có thể sửa cột Hán → Việt. Chưa dịch thì giữ Hán. Local MT dịch từng thuật ngữ,
        LLM dùng DEFAULT_PROMPT và dịch nhiều dòng mỗi lượt. Không tự ghi glossary chính.
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
                      disabled={busy}
                      title="Chọn tất cả tên chờ duyệt"
                      aria-label="Chọn tất cả tên chờ duyệt"
                      onClick={() => setChecked(allChecked ? new Set() : new Set(fresh.map((c) => c.source)))}
                      onChange={() => {}}
                    />
                  </th>
                  {["Hán", "Hán → Việt", "Loại", "Số lần", "Ngữ cảnh", "Ngữ cảnh → Việt", "Trạng thái"].map((label) => (
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
                            aria-label={`Chọn ${c.source}`}
                            disabled={busy}
                            onClick={() => toggle(c.source)}
                            onChange={() => {}}
                          />
                        ) : null}
                      </td>
                      <td className="px-2 py-1 font-medium whitespace-nowrap">{c.source}</td>
                      <td className="min-w-44 px-2 py-1">
                        {translations[c.source] ? <>
                          <Input className="w-full" aria-label={`Bản dịch ${c.source}`} value={translations[c.source].target} disabled={busy}
                            onChange={(event) => setTranslations((previous) => ({ ...previous,
                              [c.source]: { ...previous[c.source], target: event.target.value },
                            }))} />
                          <div className="mt-1 text-xs opacity-70">{translations[c.source].engine === "localmt" ? "Local MT" : "LLM"}</div>
                        </> : <span className="text-xs opacity-60">Chưa dịch</span>}
                      </td>
                      <td className="px-2 py-1 whitespace-nowrap">
                        <Badge tone={KIND[c.kind].tone}>{KIND[c.kind].text}</Badge>
                      </td>
                      <td data-numeric className="px-2 py-1 whitespace-nowrap">
                        {num(c.frequency)}
                      </td>
                      <td className="px-2 py-1 opacity-70">{c.context || "—"}</td>
                      <td className="min-w-52 px-2 py-1">
                        {translations[c.source]?.context_target || <span className="text-xs opacity-60">Chưa dịch</span>}
                        {translations[c.source]?.error && <p role="alert" className="mt-1 text-xs text-error">{translations[c.source].error}</p>}
                      </td>
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
