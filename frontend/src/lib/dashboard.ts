import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface AutomationStatus {
  id: string;
  steps: string[];
  schedule: string;
  enabled: boolean;
  last_run_at: string;
  last_run_outcome: string;
  last_run_error: string;
  last_run_stats: Record<string, number>;
}

export interface DashboardRow {
  slug: string;
  title: string;
  progress: {
    total: number;
    raw_count: number;
    translated_count: number;
    raw_pct: number;
    translated_pct: number;
  };
  crawl_problems: number;
  han_fixed: number;
  disk_total: number;
  cost_summary: { total_cost_usd: number } | null;
  automations: AutomationStatus[];
}

export interface DashboardData {
  rows: DashboardRow[];
  summary: {
    ebook_count: number;
    raw_count: number;
    translated_count: number;
    raw_pct: number;
    translated_pct: number;
    total_chapters: number;
    error_count: number;
    running_jobs: number;
  };
}

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardData>("/api/dashboard"),
    refetchInterval: 4000,
  });
}
