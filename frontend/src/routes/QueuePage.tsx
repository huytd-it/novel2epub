import { useMemo, useState } from "react";
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
  useQueue,
  type Job,
} from "@/lib/queue";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge, Dot } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconPlay, IconRetry, IconTrash } from "@/components/icons";

function JobRow({ job, onAction }: { job: Job; onAction: (job: Job, action: string) => void }) {
  const tone = jobTone(job.state);
  const running = job.state === "running";

  return (
    <tr className="border-b border-base-300 last:border-b-0 hover:bg-base-200/50">
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
      <td className="px-3 py-1.5 text-[13px] opacity-60">{job.ebook || "—"}</td>
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
              onClick={() => onAction(job, "start-now")}
              aria-label="Chạy ngay"
            />
          ) : null}
          {job.state === "failed" || job.state === "cancelled" ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconRetry />}
              onClick={() => onAction(job, "retry")}
              aria-label="Chạy lại"
            />
          ) : null}
          {running || job.state === "pending" ? (
            <Button size="sm" variant="ghost" onClick={() => onAction(job, "cancel")}>
              Hủy
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconTrash />}
              onClick={() => onAction(job, "delete")}
              aria-label="Xóa khỏi lịch sử"
            />
          )}
        </div>
      </td>
    </tr>
  );
}

function JobTable({ jobs, onAction }: { jobs: Job[]; onAction: (job: Job, action: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-base-300 bg-base-200/60">
            {["Việc", "Truyện", "Trạng thái", "Nhóm", "Thời gian", ""].map((h, i) => (
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
            <JobRow key={job.id} job={job} onAction={onAction} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function QueuePage() {
  const { data, isPending } = useQueue(1500);
  const client = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"active" | "history">("active");

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
          <Button
            variant="danger"
            icon={<IconTrash />}
            loading={bulk.isPending}
            onClick={() => bulk.mutate("/api/queue/bulk-clear-failed")}
          >
            Xóa việc lỗi
          </Button>
        </>
      }
    >
      <div className="mb-3 flex flex-wrap gap-2">
        {data
          ? Object.entries(data.workers).map(([category, count]) => {
              const runningHere = data.running.filter((j) => j.category === category).length;
              return (
                <div
                  key={category}
                  className="flex items-center gap-2 rounded-field border border-base-300 bg-base-100 px-2.5 py-1.5"
                >
                  <span className="text-[11px] tracking-wide opacity-60 uppercase">
                    {category}
                  </span>
                  <span data-numeric className="text-[13px]">
                    <span className={runningHere ? "text-warning" : "opacity-40"}>
                      {runningHere}
                    </span>
                    <span className="opacity-40">/{count}</span>
                  </span>
                </div>
              );
            })
          : null}
      </div>

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
          <JobTable jobs={jobs} onAction={onAction} />
        )}
      </Panel>
    </Page>
  );
}
