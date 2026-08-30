import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface TailscaleConfig {
  binary: string;
  port: number;
  serve_path: string;
  target: string;
  use_https: boolean;
  timeout_seconds: number;
}

export interface TailscaleOverview {
  binary: string;
  version: string;
  backend_state: string;
  tailnet: string;
  self_dns: string;
  self_ip: string;
  status_ok: boolean;
  status_error: string;
  status: Record<string, unknown> | null;
  serve: {
    on: boolean;
    funnel_on: boolean;
    config: Record<string, unknown> | null;
    raw: Record<string, unknown> | null;
  };
}

const keyStatus = ["tailscale", "status"] as const;
const keyConfig = ["tailscale", "config"] as const;

export function useTailscaleStatus() {
  return useQuery({
    queryKey: keyStatus,
    queryFn: () => api.get<TailscaleOverview>("/api/tailscale/status"),
    retry: 1,
  });
}

export function useTailscaleConfig() {
  return useQuery({
    queryKey: keyConfig,
    queryFn: () => api.get<TailscaleConfig>("/api/tailscale/config"),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: keyStatus });
    client.invalidateQueries({ queryKey: keyConfig });
  };
}

export function useSaveTailscaleConfig() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: Partial<TailscaleConfig>) =>
      api.post<TailscaleConfig>("/api/tailscale/config", { body: payload }),
    onSuccess: invalidate,
  });
}

export function useServeEnable() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload?: Record<string, unknown>) =>
      api.post<{ result: unknown; overview: TailscaleOverview }>("/api/tailscale/serve/enable", {
        body: payload ?? {},
      }),
    onSuccess: invalidate,
  });
}

export function useFunnelEnable() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload?: Record<string, unknown>) =>
      api.post<{ result: unknown; overview: TailscaleOverview }>("/api/tailscale/funnel/enable", {
        body: payload ?? {},
      }),
    onSuccess: invalidate,
  });
}

export function useServeReset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ result: unknown; overview: TailscaleOverview }>("/api/tailscale/serve/reset"),
    onSuccess: invalidate,
  });
}

export function useFunnelReset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ result: unknown; overview: TailscaleOverview }>("/api/tailscale/funnel/reset"),
    onSuccess: invalidate,
  });
}

export function useTailscaleDisable() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ result: unknown; overview: TailscaleOverview }>("/api/tailscale/disable"),
    onSuccess: invalidate,
  });
}
