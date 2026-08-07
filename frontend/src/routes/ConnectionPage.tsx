import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Page } from "@/app/Shell";
import { api, apiBase, apiToken, builtInApiBase, setApiBase, setApiToken } from "@/lib/api";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";

/**
 * Bản web chạy cùng origin nên không cần gì ở đây; bản Tauri thì có — nó nạp
 * giao diện từ `tauri://` và phải được chỉ tận nơi server đang chạy.
 */
export function ConnectionPage() {
  const toast = useToast();
  const [base, setBase] = useState(apiBase());
  const [token, setToken] = useState(apiToken());

  const probe = useQuery({
    queryKey: ["probe"],
    queryFn: () => api.get<{ ebooks: unknown[] }>("/api/ui/library"),
    retry: false,
  });

  const save = () => {
    setApiBase(base);
    setApiToken(token);
    toast("Đã lưu. Đang kiểm tra lại kết nối.");
    probe.refetch();
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
          {probe.isError ? (
            <p className="text-xs text-error">
              {probe.error instanceof Error ? probe.error.message : String(probe.error)}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button variant="primary" onClick={save}>
              Lưu và kiểm tra
            </Button>
            <Button
              onClick={() => {
                setBase("");
                setToken("");
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
