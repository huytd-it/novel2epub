import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Page } from "@/app/Shell";
import {
  localMtKey,
  useInstallLocalMtModel,
  useLocalMt,
  useSaveLocalMtConfig,
  type LocalMtConfig,
} from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { Badge } from "@/components/ui/Badge";
import { Field, Input, Select } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconChip } from "@/components/icons";

/**
 * Trang quản lý LOCAL MT CHUNG — dùng cho toàn hệ thống, không gắn ebook.
 *
 * Ba việc: (1) danh mục model kèm trạng thái tải về máy, (2) tải mới / cập
 * nhật model qua job nền, (3) model + tham số mặc định khi truyện không cấu
 * hình riêng. Danh sách model do backend đọc từ `hachimimt.translator.MODELS`
 * nên bổ sung engine/model mới chỉ cần thêm ở backend — trang tự hiển thị.
 */
export function LocalMtPage() {
  const toast = useToast();
  const client = useQueryClient();
  const { data, isPending, error } = useLocalMt();
  const install = useInstallLocalMtModel();
  const saveConfig = useSaveLocalMtConfig();

  const [confirmModel, setConfirmModel] = useState<string | null>(null);
  /** Model đang chờ job tải xong — kích hoạt polling trạng thái đĩa. */
  const [installing, setInstalling] = useState<string | null>(null);
  const [draft, setDraft] = useState<LocalMtConfig | null>(null);

  // Đồng bộ draft cấu hình với server.
  useEffect(() => {
    if (data) setDraft({ ...data.config });
  }, [data]);

  // Poll overview mỗi 3s trong lúc job tải chạy; model hiện "Đã tải" là xong.
  useEffect(() => {
    if (!installing) return;
    const timer = window.setInterval(() => client.invalidateQueries({ queryKey: localMtKey }), 3000);
    return () => window.clearInterval(timer);
  }, [installing, client]);

  useEffect(() => {
    if (!installing || !data) return;
    const model = data.engines.flatMap((e) => e.models).find((m) => m.key === installing);
    if (model?.downloaded) {
      setInstalling(null);
      toast(`Model ${model.label} đã sẵn sàng.`);
    }
  }, [installing, data, toast]);

  const models = useMemo(() => data?.engines.flatMap((e) => e.models) ?? [], [data]);
  const dirty = draft != null && data != null && JSON.stringify(draft) !== JSON.stringify(data.config);

  if (isPending) {
    return (
      <Page title="Local MT chung" loading loadingLabel="Đang đọc danh mục model">
        {null}
      </Page>
    );
  }

  if (error || !data) {
    return (
      <Page title="Không mở được Local MT">
        <Panel>
          <EmptyState
            title="Không đọc được danh mục model"
            hint={error instanceof Error ? error.message : String(error)}
          />
        </Panel>
      </Page>
    );
  }

  return (
    <Page
      title="Local MT chung"
      hint="Dịch máy cục bộ (offline) — cài đặt dùng chung mọi truyện; từng truyện vẫn có thể ghi đè ở Cài đặt → Local MT"
    >
      {data.engines.map((engine) => (
        <Panel key={engine.id} className="mb-4 overflow-hidden">
          <PanelHeader
            title={engine.label}
            hint={`Model lưu tại ${data.models_dir}`}
            actions={<Badge tone={engine.models.some((m) => m.downloaded) ? "celadon" : "gold"}>
              {engine.models.filter((m) => m.downloaded).length}/{engine.models.length} đã tải
            </Badge>}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  {["Model", "Kho (HuggingFace)", "Dung lượng", "Trạng thái", ""].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {engine.models.map((model) => (
                  <tr key={model.key} className="border-b border-base-300 last:border-b-0">
                    <td className="px-3 py-2 text-[13px] font-medium">{model.label}</td>
                    <td className="px-3 py-2 text-[12px] opacity-60" dir="ltr">
                      {model.ct2_model_id}
                    </td>
                    <td data-numeric className="px-3 py-2 text-[12px] opacity-70">
                      {model.size_mb ? `~${model.size_mb} MB` : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {installing === model.key ? (
                        <Badge tone="gold">Đang tải…</Badge>
                      ) : model.downloaded ? (
                        <Badge tone="celadon">Đã tải</Badge>
                      ) : (
                        <Badge tone="neutral">Chưa tải</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button
                        size="sm"
                        icon={model.downloaded ? undefined : <IconChip size={13} />}
                        loading={installing === model.key}
                        disabled={install.isPending}
                        onClick={() => setConfirmModel(model.key)}
                        title={model.downloaded ? "Kiểm tra & cập nhật lại file model" : "Tải model về máy"}
                      >
                        {model.downloaded ? "Cập nhật" : "Tải về"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}

      <Panel>
        <PanelHeader
          title="Cấu hình mặc định"
          hint="Áp dụng khi ebook không cấu hình riêng (tab Local MT của từng truyện ghi đè)"
          actions={
            <>
              {dirty ? (
                <Button size="sm" onClick={() => setDraft({ ...data.config })}>
                  Hủy thay đổi
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="primary"
                loading={saveConfig.isPending}
                disabled={!dirty || !draft}
                onClick={() =>
                  draft &&
                  saveConfig.mutate(draft, {
                    onSuccess: () => toast("Đã lưu cấu hình mặc định."),
                    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                  })
                }
              >
                Lưu
              </Button>
            </>
          }
        />
        {draft ? (
          <div className="grid gap-4 p-4 md:grid-cols-3">
            <Field label="Model mặc định" hint="Chọn model đã tải để dịch ngay không phải chờ tải">
              <Select
                value={draft.model_key}
                onChange={(e) => setDraft({ ...draft, model_key: e.target.value })}
              >
                {models.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}{m.downloaded ? "" : " (chưa tải)"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Beam size" hint="Cao hơn = dịch chậm hơn, hơi chuẩn hơn">
              <Input
                type="number"
                min={1}
                value={draft.beam_size}
                onChange={(e) => setDraft({ ...draft, beam_size: Number(e.target.value) })}
              />
            </Field>
            <Field label="Chia nội dung theo" hint="Cách cắt chunk khi dịch đoạn dài">
              <Select
                value={draft.chunk_mode}
                onChange={(e) => setDraft({ ...draft, chunk_mode: e.target.value })}
              >
                <option value="sentence">Câu</option>
                <option value="paragraph">Đoạn</option>
              </Select>
            </Field>
          </div>
        ) : (
          <Loading label="Đang nạp cấu hình" size="sm" />
        )}
      </Panel>

      <p className="mt-3 text-xs opacity-50">
        Tải model chạy qua hàng đợi hệ thống — theo dõi tiến độ ở trang Hàng đợi. Cập nhật chỉ tải
        lại file thiếu/thay đổi, không tải trọn bộ nếu máy đã đủ.
      </p>

      <ConfirmDialog
        open={confirmModel !== null}
        onCancel={() => setConfirmModel(null)}
        onConfirm={() => {
          if (!confirmModel) return;
          const target = models.find((m) => m.key === confirmModel);
          install.mutate(confirmModel, {
            onSuccess: () => {
              setInstalling(confirmModel);
              toast(`Đã xếp job tải ${target?.label ?? confirmModel}.`);
              setConfirmModel(null);
            },
            onError: (err) =>
              toast(err instanceof Error ? err.message : String(err), "error"),
          });
        }}
        title={models.find((m) => m.key === confirmModel)?.downloaded ? "Cập nhật model?" : "Tải model?"}
        body={
          <>
            Tải/cập nhật <strong>{models.find((m) => m.key === confirmModel)?.label}</strong> về{" "}
            <code>{data.models_dir}</code>? Job chạy nền và chiếm độc quyền hàng đợi đến khi xong.
          </>
        }
        confirmLabel="Xếp vào hàng đợi"
        pending={install.isPending}
      />
    </Page>
  );
}
