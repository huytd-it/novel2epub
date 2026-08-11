import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import { ago, duration } from "@/lib/format";
import {
  JOB_STATE_LABEL,
  jobTone,
  pendingCount,
  queueKey,
  useJobLog,
  useQueue,
  type Job,
} from "@/lib/queue";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Badge, Dot } from "@/components/ui/Badge";
import { ConfirmDialog, Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconPlay, IconRetry, IconTrash } from "@/components/icons";

const WORKER_LABEL: Record<string, string> = {
  crawl: "crawl",
  "local-mt": "local-mt",
  "ai-translate": "ai-translate",
  "ai-edit": "ai-edit",
  build: "build",
};

function JobRow({
  job,
  onAction,
  onViewLog,
}: {
  job: Job;
  onAction: (job: Job, action: string) => void;
  onViewLog: (job: Job) => void;
}) {
  const tone = jobTone(job.state);
  const running = job.state === "running";

  return (
    <tr
      className="cursor-pointer border-b border-base-300 last:border-b-0 hover:bg-base-200/50"
      title="Xem nhật ký"
      onClick={() => onViewLog(job)}
    >
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-2">
          <Dot tone={tone} pulse={running} />
          <span className="truncate text-[13px] font-medium">{job.label}</span>
        </div>
        {job.error ? (
          <p className="mt-0.5 truncate text-[11px] text-error" title={job.error}>
            {job.error}
          </p>
        ) : null}
      </td>
      <td className="px-3 py-1.5">
        <Badge tone={tone}>{job.cancelling ? "Đang hủy" : JOB_STATE_LABEL[job.state]}</Badge>
      </td>
      <td data-numeric className="px-3 py-1.5 text-xs opacity-60">
        {job.category}
      </td>
      <td data-numeric className="px-3 py-1.5 text-xs opacity-60">
        {running || job.ended_at ? duration(job.started_at, job.ended_at) : ago(job.enqueued_at)}
      </td>
      <td className="px-3 py-1.5">
        <div className="flex justify-end gap-1">
          {job.state === "pending" ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconPlay />}
              onClick={(e) => {
                e.stopPropagation();
                onAction(job, "start-now");
              }}
              aria-label="Chạy ngay"
            />
          ) : null}
          {job.state === "failed" || job.state === "cancelled" ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconRetry />}
              onClick={(e) => {
                e.stopPropagation();
                onAction(job, "retry");
              }}
              aria-label="Chạy lại"
            />
          ) : null}
          {running || job.state === "pending" ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                onAction(job, "cancel");
              }}
            >
              Hủy
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconTrash />}
              onClick={(e) => {
                e.stopPropagation();
                onAction(job, "delete");
              }}
              aria-label="Xóa khỏi lịch sử"
            />
          )}
        </div>
      </td>
    </tr>
  );
}

function JobTable({
  jobs,
  onAction,
  onViewLog,
}: {
  jobs: Job[];
  onAction: (job: Job, action: string) => void;
  onViewLog: (job: Job) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-base-300 bg-base-200/60">
            {["Việc", "Trạng thái", "Loại worker", "Thời gian", ""].map((h, i) => (
              <th
                key={h || i}
                className="px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] opacity-40 uppercase"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} onAction={onAction} onViewLog={onViewLog} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JobLogModal({ job, open, onClose }: { job: Job | null; open: boolean; onClose: () => void }) {
  const { data, isPending } = useJobLog(open && job ? job.id : null, job?.state === "running");
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [data?.log, open]);
  return (
    <Modal open={open} onClose={onClose} title={job ? `Nhật ký · ${job.label}` : "Nhật ký"} wide footer={<Button onClick={onClose}>Đóng</Button>}>
      {!job ? <EmptyState title="Chưa có nhật ký" hint="Chọn một việc trong hàng đợi để xem nhật ký." /> : isPending ? <div className="flex justify-center py-12"><Spinner /></div> : (
        <div ref={boxRef} className="scroll-slim max-h-[55vh] overflow-auto bg-base-200 px-3 py-2">
          {(data?.log ?? []).length === 0 ? <p className="py-8 text-center text-sm opacity-50">Job chưa ghi dòng log nào.</p> : (data?.log ?? []).map((line, index) => (
            <pre key={index} className={clsx("m-0 text-[12px] leading-[1.55] break-words whitespace-pre-wrap", /ERROR|CRITICAL|Traceback|failed|Lỗi/.test(line) ? "text-error" : "opacity-65")}>{line}</pre>
          ))}
        </div>
      )}
    </Modal>
  );
}

export function QueuePage() {
  const { data, isPending } = useQueue(1500);
  const client = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"active" | "history">("active");
  const [logJob, setLogJob] = useState<Job | null>(null);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);

  const act = useMutation({
    mutationFn: async ({ job, action }: { job: Job; action: string }) => {
      if (action === "delete") return api.del(`/api/queue/${job.id}`);
      return api.post(`/api/queue/${job.id}/${action}`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: queueKey }),
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const bulk = useMutation({
    mutationFn: (path: string) => api.post<{ count: number }>(path, { body: "all" }),
    onSuccess: (res) => {
      client.invalidateQueries({ queryKey: queueKey });
      toast(`Đã xử lý ${res.count} việc.`);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const clearHistory = useMutation({
    mutationFn: () => api.post<{ count: number }>("/api/queue/clear-history"),
    onSuccess: (res) => {
      setConfirmClearHistory(false);
      setLogJob(null);
      client.invalidateQueries({ queryKey: queueKey });
      toast(`Đã xóa ${res.count} việc khỏi lịch sử.`);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const updateWorkers = useMutation({
    mutationFn: ({ category, count }: { category: string; count: number }) =>
      api.post<{ count: number }>("/api/queue/workers", {
        body: { category, count },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: queueKey }),
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const active = useMemo(() => {
    if (!data) return [];
    return [...data.running, ...Object.values(data.pending).flat()];
  }, [data]);

  const failedCount = useMemo(
    () => (data?.history ?? []).filter((j) => j.state === "failed").length,
    [data],
  );

  const onAction = (job: Job, action: string) => act.mutate({ job, action });
  const jobs = tab === "active" ? active : (data?.history ?? []);

  return (
    <Page
      title="Hàng đợi"
      hint={
        data ? (
          <>
            <span data-numeric>{data.running.length}</span> đang chạy ·{" "}
            <span data-numeric>{pendingCount(data)}</span> đang chờ ·{" "}
            <span data-numeric>{data.history.length}</span> trong lịch sử
          </>
        ) : (
          "Đang đọc trạng thái hàng đợi"
        )
      }
      actions={
        <>
          {failedCount > 0 ? (
            <Button
              variant="neutral"
              icon={<IconRetry />}
              loading={bulk.isPending}
              onClick={() => bulk.mutate("/api/queue/bulk-retry-failed")}
            >
              Chạy lại {failedCount} việc lỗi
            </Button>
          ) : null}
          {failedCount > 0 ? (
            <Button
              variant="danger"
              icon={<IconTrash />}
              loading={bulk.isPending}
              onClick={() => bulk.mutate("/api/queue/bulk-clear-failed")}
            >
              Xóa việc lỗi
            </Button>
          ) : null}
          {tab === "history" && (data?.history.length ?? 0) > 0 ? (
            <Button
              variant="danger"
              icon={<IconTrash />}
              onClick={() => setConfirmClearHistory(true)}
            >
              Xóa lịch sử
            </Button>
          ) : null}
        </>
      }
    >
      <Panel className="mb-3 overflow-hidden">
        <PanelHeader
          title="Số lượng worker của Hàng đợi"
          actions={<span className="text-xs opacity-50">0 = tạm dừng loại worker</span>}
        />
        <div className="flex flex-wrap gap-2 p-3">
        {data
          ? data.categories.map((category) => {
              const count = data.workers[category] ?? 0;
              const runningHere = data.running.filter((j) => j.category === category).length;
              return (
                <div
                  key={category}
                  className="flex items-center gap-3 rounded-field border border-base-300 bg-base-100 py-1 pl-2.5 pr-1"
                >
                  <span className="min-w-20 text-[11px] tracking-wide opacity-60">
                    {WORKER_LABEL[category] ?? category}
                  </span>
                  <span data-numeric className={clsx("text-xs", runningHere ? "text-warning" : "opacity-40")}>{runningHere} chạy</span>
                  <div className="flex items-center rounded-field border border-base-300">
                    <button
                      type="button"
                      className="h-7 w-7 text-sm opacity-60 hover:bg-base-200 hover:opacity-100 disabled:opacity-25"
                      disabled={updateWorkers.isPending || count <= 0}
                      onClick={() => updateWorkers.mutate({ category, count: count - 1 })}
                      aria-label={`Giảm worker ${category}`}
                    >
                      −
                    </button>
                    <span data-numeric className="w-7 text-center text-[13px] font-medium">{count}</span>
                    <button
                      type="button"
                      className="h-7 w-7 text-sm opacity-60 hover:bg-base-200 hover:opacity-100 disabled:opacity-25"
                      disabled={updateWorkers.isPending}
                      onClick={() => updateWorkers.mutate({ category, count: count + 1 })}
                      aria-label={`Tăng worker ${category}`}
                    >
                      +
                    </button>
                  </div>
                </div>
              );
            })
          : null}
        </div>
      </Panel>

      <Panel className="overflow-hidden">
        <PanelHeader
          title={
            <span className="flex gap-1">
              {(["active", "history"] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTab(key)}
                  className={clsx(
                    "rounded-selector px-2 py-0.5 text-[13px] transition-colors",
                    tab === key ? "bg-warning/15 text-warning" : "opacity-60 hover:font-medium",
                  )}
                >
                  {key === "active" ? "Đang chạy & chờ" : "Lịch sử"}
                </button>
              ))}
            </span>
          }
        />
        {isPending ? (
          <EmptyState title="Đang tải" />
        ) : jobs.length === 0 ? (
          <EmptyState
            title={tab === "active" ? "Không có việc nào đang chạy" : "Lịch sử trống"}
            hint={
              tab === "active"
                ? "Chạy crawl, dịch hoặc build từ trang truyện để đưa việc vào hàng đợi."
                : undefined
            }
          />
        ) : (
          <JobTable jobs={jobs} onAction={onAction} onViewLog={setLogJob} />
        )}
      </Panel>

      <JobLogModal job={logJob} open={logJob !== null} onClose={() => setLogJob(null)} />
      <ConfirmDialog
        open={confirmClearHistory}
        onCancel={() => setConfirmClearHistory(false)}
        onConfirm={() => clearHistory.mutate()}
        title="Xóa toàn bộ lịch sử?"
        body={
          <p>
            {data?.history.length ?? 0} việc đã kết thúc sẽ bị xóa vĩnh viễn. Việc đang chạy và đang chờ không bị ảnh hưởng.
          </p>
        }
        confirmLabel="Xóa lịch sử"
        destructive
        pending={clearHistory.isPending}
      />
    </Page>
  );
}
