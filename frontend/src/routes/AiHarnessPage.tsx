import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { AssistantPanel } from "@/components/AssistantPanel";
import { DiffText } from "@/components/DiffText";
import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

type RunStatus = "queued" | "running" | "completed" | "partial" | "failed";
type Issue = {
  id: number;
  chapter_index: number;
  category: string;
  severity: string;
  kind: "text" | "glossary";
  status: "pending" | "blocked" | "applied" | "dismissed";
  source: string;
  current: string;
  suggestion: string;
  reason: string;
  before_text: string;
  after_text: string;
  error: string;
};
type ChapterResult = { chapter_index: number; status: string; issue_count: number; error: string };
type Run = {
  id: number;
  ebook_slug: string;
  workflow_version: number;
  status: RunStatus;
  total: number;
  processed: number;
  failed: number;
  created_at: string;
  chapters: ChapterResult[];
  issues: Issue[];
};
type Preview = {
  kind: "text" | "glossary";
  token: string;
  stale?: number;
  items?: { id: number; chapter_index: number; before: string; after: string; stale: boolean }[];
  entries?: { source: string; target: string; existing_target: string; count: number; chapters: number; error: string }[];
  errors?: number;
  total_matches?: number;
  samples?: { groups: { items: { before: string; after: string; chapter_index: number }[] }[]; truncated: boolean };
};

const categoryName: Record<string, string> = {
  glossary: "Glossary", consistency: "Nhất quán", mistranslation: "Sai nghĩa",
  hanviet: "Hán Việt", fluency: "Văn phong", other: "Khác",
};
const statusName: Record<string, string> = {
  queued: "Chờ", running: "Đang chạy", completed: "Hoàn tất", partial: "Có chương lỗi",
  failed: "Thất bại", clean: "Sạch", issues: "Có lỗi", blocked: "Cần sửa tay",
  applied: "Đã áp dụng", dismissed: "Đã bỏ qua", pending: "Chờ duyệt",
};

function downloadReport(run: Run) {
  const lines = [`# AI Harness — ${run.ebook_slug}`, "", `Lượt #${run.id} · ${statusName[run.status]} · workflow v${run.workflow_version}`, ""];
  for (const chapter of run.chapters) {
    lines.push(`## Chương ${chapter.chapter_index} — ${statusName[chapter.status] ?? chapter.status}`);
    if (chapter.error) lines.push(`Lỗi: ${chapter.error}`);
    for (const issue of run.issues.filter((item) => item.chapter_index === chapter.chapter_index)) {
      lines.push("", `- **${categoryName[issue.category] ?? issue.category} / ${issue.severity}** (${issue.status}): ${issue.reason}`,
        `  - Hiện tại: ${issue.current}`, `  - Đề xuất: ${issue.suggestion}`);
    }
    lines.push("");
  }
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `ai-harness-${run.ebook_slug}-${run.id}.md`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AiHarnessPage() {
  const { slug = "" } = useParams();
  const toast = useToast();
  const client = useQueryClient();
  const [tab, setTab] = useState<"review" | "chat">("review");
  const [runId, setRunId] = useState<number | null>(null);
  const [category, setCategory] = useState("all");
  const [chapter, setChapter] = useState("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<Preview | null>(null);

  const base = `/api/ui/ebooks/${encodeURIComponent(slug)}/ai-harness/runs`;
  const runs = useQuery({
    queryKey: ["ai-harness-runs", slug],
    queryFn: () => api.get<{ runs: Omit<Run, "chapters" | "issues">[] }>(base),
    enabled: Boolean(slug), refetchInterval: 5000,
  });
  useEffect(() => {
    if (runId == null && runs.data?.runs.length) setRunId(runs.data.runs[0].id);
  }, [runId, runs.data]);
  const detail = useQuery({
    queryKey: ["ai-harness-run", slug, runId],
    queryFn: () => api.get<Run>(`${base}/${runId}`),
    enabled: Boolean(slug) && runId != null,
    refetchInterval: (query) => ["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false,
  });
  const run = detail.data;
  const start = useMutation({
    mutationFn: () => api.post<{ run_id: number }>(base),
    onSuccess: async (result) => {
      setRunId(result.run_id); setSelected(new Set());
      await client.invalidateQueries({ queryKey: ["ai-harness-runs", slug] });
      toast("Đã xếp lượt rà soát toàn truyện vào hàng đợi.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });
  const previewMutation = useMutation({
    mutationFn: (ids: number[]) => api.post<Preview>(`${base}/${runId}/preview`, { body: { ids } }),
    onSuccess: setPreview,
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });
  const applyMutation = useMutation({
    mutationFn: (input: { ids: number[]; token: string }) => api.post<{ applied: number }>(`${base}/${runId}/apply`, { body: input }),
    onSuccess: async () => {
      setPreview(null); setSelected(new Set());
      await client.invalidateQueries({ queryKey: ["ai-harness-run", slug, runId] });
      toast("Đã áp dụng các đề xuất đã chọn.");
    },
    onError: (err) => {
      client.invalidateQueries({ queryKey: ["ai-harness-run", slug, runId] });
      toast(err instanceof Error ? err.message : String(err), "error");
    },
  });
  const dismissMutation = useMutation({
    mutationFn: (ids: number[]) => api.post(`${base}/${runId}/dismiss`, { body: { ids } }),
    onSuccess: async () => {
      setSelected(new Set());
      await client.invalidateQueries({ queryKey: ["ai-harness-run", slug, runId] });
      toast("Đã bỏ qua các đề xuất đã chọn.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const visible = useMemo(() => (run?.issues ?? []).filter((issue) =>
    (category === "all" || issue.category === category) &&
    (chapter === "all" || issue.chapter_index === Number(chapter))), [run?.issues, category, chapter]);
  const picked = useMemo(() => (run?.issues ?? []).filter((issue) => selected.has(issue.id)), [run?.issues, selected]);
  const mixed = new Set(picked.map((issue) => issue.kind)).size > 1;
  const canApply = picked.length > 0 && !mixed && picked.every((issue) => issue.status === "pending");
  const canDismiss = picked.length > 0 && picked.every((issue) => ["pending", "blocked"].includes(issue.status));
  const toggle = (id: number) => setSelected((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <Page title="AI Harness" hint="Rà soát bản dịch toàn truyện, xem diff và duyệt sửa theo từng lỗi.">
      <div className="mb-4 flex gap-2 border-b border-base-300 pb-2" role="tablist" aria-label="AI Harness">
        <Button variant={tab === "review" ? "primary" : "ghost"} role="tab" aria-selected={tab === "review"} onClick={() => setTab("review")}>Rà soát</Button>
        <Button variant={tab === "chat" ? "primary" : "ghost"} role="tab" aria-selected={tab === "chat"} onClick={() => setTab("chat")}>Trợ lý và tool</Button>
      </div>
      {tab === "chat" ? (
        <div className="h-[calc(100dvh-11rem)] min-h-[520px] overflow-hidden rounded-box border border-base-300">
          <AssistantPanel ebookSlug={slug} />
        </div>
      ) : (
        <div className="space-y-4">
          <section className="rounded-box border border-base-300 bg-base-100 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" loading={start.isPending} disabled={runs.data?.runs.some((item) => ["queued", "running"].includes(item.status))} onClick={() => start.mutate()}>
                Rà soát toàn truyện
              </Button>
              <span className="text-xs opacity-60">Workflow v1 · phát hiện lỗi dịch và nhất quán · mọi sửa đổi cần duyệt diff</span>
              <Link to="/queue" className="link link-hover ml-auto text-xs">Xem hàng đợi</Link>
            </div>
            {runs.data?.runs.length ? (
              <div className="mt-3 flex flex-wrap gap-2" aria-label="Lịch sử rà soát">
                {runs.data.runs.map((item) => <Button key={item.id} size="sm" variant={runId === item.id ? "neutral" : "ghost"} onClick={() => { setRunId(item.id); setSelected(new Set()); }}>
                  #{item.id} · {statusName[item.status] ?? item.status}
                </Button>)}
              </div>
            ) : <p className="mt-3 text-sm opacity-60">Chưa có lượt rà soát nào.</p>}
          </section>

          {run ? <>
            <section className="rounded-box border border-base-300 bg-base-100 p-4">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <strong>Lượt #{run.id}</strong><span>{statusName[run.status] ?? run.status}</span>
                <span>{run.processed}/{run.total} chương</span><span>{run.failed} chương lỗi</span>
                <Button size="sm" className="ml-auto" onClick={() => downloadReport(run)}>Xuất báo cáo .md</Button>
              </div>
              <progress className="progress progress-primary mt-3 w-full" value={run.processed} max={run.total || 1} aria-label="Tiến độ rà soát" />
              <div className="mt-3 flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
                {run.chapters.map((item) => <button type="button" key={item.chapter_index} className="badge badge-outline cursor-pointer" title={item.error || statusName[item.status] || item.status} onClick={() => setChapter(String(item.chapter_index))}>
                  {item.chapter_index}: {statusName[item.status] ?? item.status}{item.issue_count ? ` (${item.issue_count})` : ""}
                </button>)}
              </div>
              {run.chapters.some((item) => item.error) ? <ul className="mt-3 space-y-1 text-xs text-error">
                {run.chapters.filter((item) => item.error).map((item) => <li key={item.chapter_index}>Chương {item.chapter_index}: {item.error}</li>)}
              </ul> : null}
            </section>
            <section className="rounded-box border border-base-300 bg-base-100 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="mr-auto font-display text-lg">Đề xuất ({visible.length})</h2>
                <select className="select select-sm" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Lọc loại lỗi">
                  <option value="all">Mọi loại</option>{Object.entries(categoryName).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
                </select>
                <select className="select select-sm" value={chapter} onChange={(e) => setChapter(e.target.value)} aria-label="Lọc chương">
                  <option value="all">Mọi chương</option>{run.chapters.map((item) => <option key={item.chapter_index} value={item.chapter_index}>Chương {item.chapter_index}</option>)}
                </select>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => setSelected(new Set(visible.filter((item) => ["pending", "blocked"].includes(item.status)).map((item) => item.id)))}>Chọn lỗi đang hiển thị</Button>
                <Button size="sm" onClick={() => setSelected(new Set())}>Bỏ chọn</Button>
                <Button size="sm" variant="primary" disabled={!canApply} loading={previewMutation.isPending} onClick={() => previewMutation.mutate(picked.map((item) => item.id))}>Xem trước {picked.length} sửa đổi</Button>
                <Button size="sm" disabled={!canDismiss} loading={dismissMutation.isPending} onClick={() => dismissMutation.mutate(picked.map((item) => item.id))}>Bỏ qua</Button>
                {mixed ? <span className="self-center text-xs text-warning">Duyệt lỗi nội dung và Glossary thành hai đợt.</span> : null}
              </div>
              <div className="mt-3 space-y-2">
                {visible.map((issue) => <article key={issue.id} className="rounded-box border border-base-300 p-3">
                  <div className="flex items-start gap-2">
                    <input type="checkbox" className="checkbox checkbox-sm mt-0.5" checked={selected.has(issue.id)} disabled={!(["pending", "blocked"].includes(issue.status))} onChange={() => toggle(issue.id)} aria-label={`Chọn lỗi ${issue.id}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap gap-2 text-xs">
                        <strong>Chương {issue.chapter_index}</strong><span>{categoryName[issue.category] ?? issue.category}</span>
                        <span>{issue.severity}</span><span>{statusName[issue.status] ?? issue.status}</span>
                      </div>
                      <p className="mt-1 text-sm">{issue.reason || "Đề xuất chỉnh sửa"}</p>
                      {issue.source ? <p className="mt-1 text-xs opacity-60">Gốc: {issue.source}</p> : null}
                      <div className="mt-2 grid gap-2 text-sm md:grid-cols-2">
                        <div className="rounded bg-error/5 p-2"><span className="mb-1 block text-xs opacity-60">Hiện tại</span><DiffText before={issue.before_text || issue.current} after={issue.after_text || issue.suggestion} mode="removed" /></div>
                        <div className="rounded bg-success/5 p-2"><span className="mb-1 block text-xs opacity-60">Đề xuất</span><DiffText before={issue.before_text || issue.current} after={issue.after_text || issue.suggestion} mode="added" /></div>
                      </div>
                      {issue.error ? <p className="mt-2 text-xs text-warning">{issue.error} — cần sửa tay trong <Link className="link" to={`/ebooks/${slug}/chapters/${issue.chapter_index}`}>trang chương</Link>.</p> : null}
                    </div>
                  </div>
                </article>)}
                {!visible.length ? <p className="py-6 text-center text-sm opacity-60">Không có đề xuất trong bộ lọc này.</p> : null}
              </div>
            </section>
          </> : null}
        </div>
      )}

      <Modal open={preview != null} onClose={() => setPreview(null)} title="Xem trước thay đổi" wide footer={<>
        <Button onClick={() => setPreview(null)}>Đóng</Button>
        <Button variant="primary" loading={applyMutation.isPending} disabled={!preview || (preview.kind === "text" && !!preview.stale) || (preview.kind === "glossary" && !!preview.errors)} onClick={() => preview && applyMutation.mutate({ ids: picked.map((item) => item.id), token: preview.token })}>Áp dụng {picked.length} đề xuất</Button>
      </>}>
        {preview?.kind === "text" ? <div className="space-y-3">
          {preview.items?.map((item) => <div key={item.id} className="rounded border border-base-300 p-2 text-sm">
            <p className="mb-2 text-xs">Chương {item.chapter_index}{item.stale ? " · Bản dịch đã đổi, cần quét lại" : ""}</p>
            <p><DiffText before={item.before} after={item.after} mode="removed" /></p>
            <p className="mt-2"><DiffText before={item.before} after={item.after} mode="added" /></p>
          </div>)}
        </div> : preview?.kind === "glossary" ? <div className="space-y-3 text-sm">
          <p>{preview.total_matches ?? 0} chỗ khớp trong bản dịch cũ.</p>
          {preview.entries?.map((item) => <div key={item.source} className="rounded border border-base-300 p-2">
            <strong>{item.source}</strong><p><DiffText before={item.existing_target} after={item.target} /></p>
            <p className="text-xs opacity-60">{item.count} chỗ · {item.chapters} chương {item.error ? `· ${item.error}` : ""}</p>
          </div>)}
          {preview.samples?.groups.flatMap((group) => group.items).slice(0, 20).map((item, index) => <div key={index} className="rounded border border-base-300 p-2">
            <p className="text-xs opacity-60">Chương {item.chapter_index}</p><DiffText before={item.before} after={item.after} />
          </div>)}
          {preview.samples?.truncated ? <p className="text-xs opacity-60">Chỉ hiển thị 20 đoạn mẫu.</p> : null}
        </div> : null}
      </Modal>
    </Page>
  );
}
