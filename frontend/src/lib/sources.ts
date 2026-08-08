import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface SourcePreset {
  name: string;
  engine: string;
  url: string;
  domains: string;
  chapter_link_pattern: string;
  content_selector: string;
  toc_selector: string;
  chapter_title_selector: string;
  title_selector: string;
  author_selector: string;
  desc_selector: string;
  cover_selector: string;
  encoding: string;
  user_agent: string;
  headless: boolean;
  magic: boolean;
  js_code: string;
  delay_seconds: number;
  next_page_selector: string;
  next_page_url_pattern: string;
  max_pages_per_chapter: number;
  scrapling_mode: string;
  solve_cloudflare: boolean;
  network_idle: boolean;
  impersonate: string;
  proxy: string;
  dns_over_https: boolean;
  concurrency_cap: number;
  strip_patterns: string[];
}

export interface ValidationEntry {
  ok: boolean;
  message: string;
  checked_at: number;
}

export interface SourcesOverview {
  presets: SourcePreset[];
  usage: Record<string, string[]>;
  validation: Record<string, ValidationEntry>;
}

const key = ["sources"] as const;

export function useSources() {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<SourcesOverview>("/api/ui/sources"),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: key });
}

export function useSavePreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (preset: Partial<SourcePreset> & { name: string }) =>
      api.post<SourcePreset>("/api/ui/sources", { body: preset }),
    onSuccess: invalidate,
  });
}

export function useDeletePreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) => api.post<{ ok: boolean }>(`/api/ui/sources/${encodeURIComponent(name)}/delete`),
    onSuccess: invalidate,
  });
}

export function useClonePreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { name: string; newName: string }) =>
      api.post<SourcePreset>(`/api/ui/sources/${encodeURIComponent(vars.name)}/clone`, {
        body: { new_name: vars.newName },
      }),
    onSuccess: invalidate,
  });
}

export function useTestPreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { name: string; tocUrl: string }) =>
      api.post<{ started: boolean }>(`/api/ui/sources/${encodeURIComponent(vars.name)}/test`, {
        body: { toc_url: vars.tocUrl },
      }),
    onSuccess: invalidate,
  });
}

export const EMPTY_PRESET: SourcePreset = {
  name: "",
  engine: "scrapling",
  url: "",
  domains: "",
  chapter_link_pattern: ".*",
  content_selector: "",
  toc_selector: "",
  chapter_title_selector: "",
  title_selector: "",
  author_selector: "",
  desc_selector: "",
  cover_selector: "",
  encoding: "",
  user_agent: "",
  headless: false,
  magic: false,
  js_code: "",
  delay_seconds: 1,
  next_page_selector: "",
  next_page_url_pattern: "",
  max_pages_per_chapter: 10,
  scrapling_mode: "stealthy",
  solve_cloudflare: false,
  network_idle: false,
  impersonate: "",
  proxy: "",
  dns_over_https: false,
  concurrency_cap: 0,
  strip_patterns: [],
};
