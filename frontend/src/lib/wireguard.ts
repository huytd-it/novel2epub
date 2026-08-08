import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase, apiToken } from "./api";

export interface WireGuardConfig {
  enabled: boolean;
  profiles_dir: string;
  wg_exe: string;
  manage_service: boolean;
  service_timeout_seconds: number;
  lock_timeout_seconds: number;
  wgcf_enabled: boolean;
  wgcf_executable: string;
  wgcf_output: string;
  wgcf_timeout_seconds: number;
  wgcf_argv_configured: boolean;
  wgcf_argv_count: number;
}

export interface WireGuardProfile {
  id: string;
  filename: string;
  source: string;
  enabled: boolean;
  position: number;
  status: string;
  error: string;
  activated_at: string;
  last_error_at: string;
  created_at: string;
  updated_at: string;
}

const key = ["wireguard"] as const;

export function useWireGuardOverview() {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<{ config: WireGuardConfig; profiles: WireGuardProfile[] }>("/api/ui/wireguard"),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: key });
}

export function useSaveWireGuardSettings() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<{ ok: boolean }>("/api/ui/wireguard/settings", { body: payload }),
    onSuccess: invalidate,
  });
}

/** Multipart — dùng `fetch` trực tiếp vì `api.post` chỉ hỗ trợ JSON/form-urlencoded. */
export function useImportWireGuardProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (vars: { file: File; name: string }) => {
      const form = new FormData();
      form.append("file", vars.file);
      form.append("name", vars.name);
      const token = apiToken();
      const res = await fetch(`${apiBase()}/api/ui/wireguard/import`, {
        method: "POST",
        body: form,
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `${res.status} ${res.statusText}`);
      }
      return res.json() as Promise<{ ok: boolean }>;
    },
    onSuccess: invalidate,
  });
}

export function useDiscoverProfiles() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ added: number }>("/api/ui/wireguard/discover"),
    onSuccess: invalidate,
  });
}

export function useProvisionProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (label: string) => api.post<{ ok: boolean }>("/api/ui/wireguard/provision", { body: { label } }),
    onSuccess: invalidate,
  });
}

export function useSetProfileEnabled() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { id: string; enabled: boolean }) =>
      api.post<{ ok: boolean }>(`/api/ui/wireguard/${vars.id}/${vars.enabled ? "enable" : "disable"}`),
    onSuccess: invalidate,
  });
}

export function useSetProfilePosition() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { id: string; position: number }) =>
      api.post<{ ok: boolean }>(`/api/ui/wireguard/${vars.id}/position`, { body: { position: vars.position } }),
    onSuccess: invalidate,
  });
}

export function useActivateProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean }>(`/api/ui/wireguard/${id}/activate`),
    onSuccess: invalidate,
  });
}

export function useRotateProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/ui/wireguard/rotate"),
    onSuccess: invalidate,
  });
}

export function useDeleteProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean }>(`/api/ui/wireguard/${id}/delete`),
    onSuccess: invalidate,
  });
}
