import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type JobState = "pending" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: string;
  category: string;
  step: string;
  label: string;
  ebook: string;
  lock_ebook: boolean;
  chapter_indexes: number[];
  ebook_code: string;
  chapter_codes: string[];
  state: JobState;
  enqueued_at: number | null;
  started_at: number | null;
  ended_at: number | null;
  error: string | null;
  cancelling: boolean;
  outcome?: unknown;
}

export interface QueueSnapshot {
  categories: string[];
  running: Job[];
  pending: Record<string, Job[]>;
  history: Job[];
  workers: Record<string, number>;
}

export const queueKey = ["queue"] as const;

export function useQueue(pollMs = 2000) {
  return useQuery({
    queryKey: queueKey,
    queryFn: () => api.get<QueueSnapshot>("/api/queue"),
    refetchInterval: pollMs,
    staleTime: 0,
  });
}

export function pendingCount(snapshot: QueueSnapshot | undefined): number {
  if (!snapshot) return 0;
  return Object.values(snapshot.pending).reduce((sum, list) => sum + list.length, 0);
}

export function jobTone(state: JobState): "neutral" | "gold" | "celadon" | "vermilion" {
  if (state === "running") return "gold";
  if (state === "done") return "celadon";
  if (state === "failed") return "vermilion";
  return "neutral";
}

export const JOB_STATE_LABEL: Record<JobState, string> = {
  pending: "Chờ",
  running: "Đang chạy",
  done: "Xong",
  failed: "Lỗi",
  cancelled: "Đã hủy",
};
