import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Page } from "@/app/Shell";
import { ApiError, api, apiBase, apiToken, builtInApiBase, setApiBase, setApiToken } from "@/lib/api";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";

type ConnectionMode = "same-origin" | "tailnet" | "funnel";

function normalizeApiBase(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  const url = new URL(trimmed);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.protocol !== "https:" && !(local && url.protocol === "http:")) {
    throw new Error("Server từ xa phải dùng HTTPS. HTTP chỉ được phép với localhost.");
  }
  return url.toString().replace(/\/+$/, "");
}

function connectionError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Token không hợp lệ hoặc đã đổi. Hãy nhập lại token API của server.";
  }
  if (error instanceof TypeError) {
    return "Không tới được server. Kiểm tra Tailscale, HTTPS, địa chỉ và CORS của backend.";
  }
  return error instanceof Error ? error.message : String(error);
}

/** Cấu hình một client SPA/Tauri tới backend local, tailnet hoặc Funnel. */
export function ConnectionPage() {
  const toast = useToast();
  const [base, setBase] = useState(apiBase());
  const [token, setToken] = useState(apiToken());
  const [mode, setMode] = useState<ConnectionMode>(apiBase() ? "tailnet" : "same-origin");
  const [validationError, setValidationError] = useState("");

  const probe = useQuery({
    queryKey: ["probe"],
    queryFn: () => api.get<{ ebooks: unknown[] }>("/api/ui/library"),
    retry: false,
  });

  const save = () => {
    try {
      const normalized = mode === "same-origin" ? "" : normalizeApiBase(base);
      if (mode !== "same-origin" && !normalized) throw new Error("Hãy nhập địa chỉ server.");
      setValidationError("");
      setBase(normalized);
      setApiBase(normalized);
      setApiToken(token);
      toast("Đã lưu. Đang kiểm tra lại kết nối.");
      probe.refetch();
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <Page
      title="Kết nối"
      hint="Nơi giao diện này tìm thấy server novel2epub"
      actions={
        probe.isSuccess ? (
          <Badge tone="celadon">Kết nối được</Badge>
        ) : probe.isError ? (
          <Badge tone="vermilion">Không kết nối được</Badge>
        ) : (
          <Badge>Đang kiểm tra</Badge>
        )
      }
    >
      <Panel className="max-w-2xl">
        <PanelHeader
          title="Địa chỉ server"
          hint="Để trống nếu giao diện chạy cùng máy chủ với API."
        />
        <div className="space-y-4 p-3">
          <div className="join flex w-full" aria-label="Kiểu kết nối">
            {([
              ["same-origin", "Cùng server"],
              ["tailnet", "Tailscale riêng"],
              ["funnel", "Funnel công khai"],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`btn btn-sm join-item flex-1 ${mode === value ? "btn-active" : ""}`}
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value);
                  setValidationError("");
                  if (value === "same-origin") setBase("");
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {mode === "tailnet" ? (
            <p className="text-xs opacity-65">
              Dùng hostname HTTPS <code>https://may-chu.tailnet.ts.net</code>. Trình duyệt mở frontend
              Vercel chỉ kết nối được khi chính thiết bị đó đã đăng nhập Tailscale.
            </p>
          ) : mode === "funnel" ? (
            <p className="text-xs text-warning">
              Funnel đưa API ra Internet. Bắt buộc dùng token mạnh, HTTPS và chỉ cho phép chính xác
              origin Vercel trong CORS; không dùng dấu <code>*</code>.
            </p>
          ) : (
            <p className="text-xs opacity-65">Dùng khi FastAPI đang phục vụ frontend tại cùng origin.</p>
          )}
          <Field
            label="Địa chỉ"
            hint={
              builtInApiBase()
                ? `Bỏ trống để dùng địa chỉ nung sẵn lúc build: ${builtInApiBase()}`
                : "Ví dụ https://xuong.tailnet-cua-ban.ts.net khi giao diện chạy trên host khác."
            }
          >
            <Input
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder={builtInApiBase() || "http://127.0.0.1:8010"}
              spellCheck={false}
              disabled={mode === "same-origin"}
            />
          </Field>
          <Field
            label="Token API"
            hint="Chỉ cần khi gọi từ máy khác. Lấy token ở Cài đặt > API của server."
          >
            <Input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Bỏ trống nếu chạy cùng máy"
              spellCheck={false}
            />
          </Field>
          {validationError ? <p className="text-xs text-error">{validationError}</p> : null}
          {probe.isError ? (
            <p className="text-xs text-error">{connectionError(probe.error)}</p>
          ) : null}
          <div className="flex gap-2">
            <Button variant="primary" onClick={save}>
              Lưu và kiểm tra
            </Button>
            <Button
              onClick={() => {
                setMode("same-origin");
                setBase("");
                setToken("");
                setValidationError("");
                setApiBase("");
                setApiToken("");
                toast("Đã xóa cấu hình, quay về dùng cùng origin.");
                probe.refetch();
              }}
            >
              Về mặc định
            </Button>
          </div>
        </div>
      </Panel>
    </Page>
  );
}
