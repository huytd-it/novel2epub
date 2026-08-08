import { useEffect, useState } from "react";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import {
  useAutomationOverview,
  useCreateAutomation,
  useDeleteAutomation,
  useRunAutomationNow,
  useUpdateAutomation,
  useValidateSchedule,
  type Automation,
} from "@/lib/automation";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Input, InputWithIcon } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconPlay, IconPlus, IconSearch, IconTrash } from "@/components/icons";

const OUTCOME_TONE: Record<string, "gold" | "celadon" | "vermilion" | "neutral"> = {
  success: "celadon",
  failure: "vermilion",
  partial: "gold",
};
const OUTCOME_LABEL: Record<string, string> = {
  success: "thành công",
  failure: "lỗi",
  partial: "một phần",
};

const SCHEDULE_PRESETS = [
  { label: "Mỗi 15p", cron: "*/15 * * * *" },
  { label: "Mỗi 30p", cron: "*/30 * * * *" },
  { label: "Mỗi giờ", cron: "0 * * * *" },
  { label: "Hàng ngày 03:00", cron: "0 3 * * *" },
  { label: "CN 03:00", cron: "0 3 * * 0" },
  { label: "Thủ công", cron: "manual" },
];

/* ── Modal thêm automation ───────────────────────────────────────────── */

function AddAutomationModal({
  open,
  onClose,
  ebooks,
  steps,
}: {
  open: boolean;
  onClose: () => void;
  ebooks: { slug: string; title: string }[];
  steps: string[];
}) {
  const [ebook, setEbook] = useState("");
  const [search, setSearch] = useState("");
  const [selectedSteps, setSelectedSteps] = useState<Set<string>>(new Set(steps));
  const [crawlWorkers, setCrawlWorkers] = useState("4");
  const [translateWorkers, setTranslateWorkers] = useState("4");
  const [schedule, setSchedule] = useState("manual");
  const create = useCreateAutomation();
  const validate = useValidateSchedule();
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setEbook(ebooks[0]?.slug ?? "");
      setSearch("");
      setSelectedSteps(new Set(steps));
      setCrawlWorkers("4");
      setTranslateWorkers("4");
      setSchedule("manual");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset chỉ lúc mở modal
  }, [open]);

  useEffect(() => {
    if (open) validate.mutate(schedule);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- debounce đơn giản theo schedule
  }, [schedule, open]);

  const filteredEbooks = ebooks.filter((e) => {
    const q = search.trim().toLowerCase();
    return !q || e.title.toLowerCase().includes(q) || e.slug.toLowerCase().includes(q);
  });

  const toggleStep = (step: string) =>
    setSelectedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(step)) next.delete(step);
      else next.add(step);
      return next;
    });

  const submit = () => {
    if (!ebook) {
      toast("Chưa chọn truyện.", "error");
      return;
    }
    if (validate.data && !validate.data.valid) {
      toast("Lịch không hợp lệ.", "error");
      return;
    }
    create.mutate(
      {
        ebook,
        steps: [...selectedSteps],
        schedule: schedule.trim() || "manual",
        crawl_workers: Number(crawlWorkers) || 4,
        translate_workers: Number(translateWorkers) || 4,
      },
      {
        onSuccess: () => {
          toast("Đã tạo automation.");
          onClose();
        },
        onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Thêm automation"
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={create.isPending} onClick={submit}>
            Tạo automation
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <fieldset className="rounded-box border border-base-300 p-3">
          <legend className="px-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">Truyện</legend>
          <InputWithIcon
            icon={<IconSearch size={13} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm theo tên hoặc slug"
            className="mb-2 w-full"
          />
          <select
            value={ebook}
            onChange={(e) => setEbook(e.target.value)}
            size={5}
            className="select w-full"
          >
            {filteredEbooks.map((e) => (
              <option key={e.slug} value={e.slug}>
                {e.title}
                {e.title !== e.slug ? ` · ${e.slug}` : ""}
              </option>
            ))}
          </select>
        </fieldset>

        <fieldset className="rounded-box border border-base-300 p-3">
          <legend className="px-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">Các bước</legend>
          <div className="space-y-1.5">
            {steps.map((step) => (
              <div
                key={step}
                className="flex flex-wrap items-center justify-between gap-2 rounded-field border border-base-300 px-2.5 py-1.5"
              >
                <label className="flex items-center gap-2 text-[13px] font-medium">
                  <input
                    type="checkbox"
                    checked={selectedSteps.has(step)}
                    onChange={() => toggleStep(step)}
                    className="checkbox checkbox-xs"
                  />
                  {step}
                </label>
                {step === "crawl-new" ? (
                  <label className="flex items-center gap-1.5 text-xs opacity-70">
                    Số crawler
                    <Input
                      type="number"
                      min={1}
                      max={64}
                      value={crawlWorkers}
                      onChange={(e) => setCrawlWorkers(e.target.value)}
                      className="w-16"
                    />
                  </label>
                ) : null}
                {step === "translate-pending" ? (
                  <label className="flex items-center gap-1.5 text-xs opacity-70">
                    Số luồng dịch
                    <Input
                      type="number"
                      min={1}
                      max={64}
                      value={translateWorkers}
                      onChange={(e) => setTranslateWorkers(e.target.value)}
                      className="w-16"
                    />
                  </label>
                ) : null}
              </div>
            ))}
          </div>
        </fieldset>

        <fieldset className="rounded-box border border-base-300 p-3">
          <legend className="px-1 text-[11px] font-semibold tracking-wide uppercase opacity-60">Lịch chạy</legend>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SCHEDULE_PRESETS.map((p) => (
              <Button key={p.cron} size="sm" onClick={() => setSchedule(p.cron)}>
                {p.label}
              </Button>
            ))}
          </div>
          <Input
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            spellCheck={false}
            placeholder="manual hoặc cron 5 trường"
            className="w-full font-mono"
          />
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-xs opacity-50">
              Thứ tự: phút, giờ, ngày, tháng, thứ. Ví dụ <code>0 3 * * *</code>.
            </span>
            {validate.data ? (
              <span className={clsx("text-xs font-medium", validate.data.valid ? "text-success" : "text-error")}>
                {validate.data.valid ? "Hợp lệ" : "Cron không hợp lệ"}
              </span>
            ) : null}
          </div>
        </fieldset>
      </div>
    </Modal>
  );
}

/* ── Hàng automation ─────────────────────────────────────────────────── */

function AutomationRow({ a, onDelete }: { a: Automation; onDelete: () => void }) {
  const update = useUpdateAutomation();
  const runNow = useRunAutomationNow();
  const toast = useToast();

  return (
    <tr className="border-b border-base-300 last:border-b-0">
      <td className="px-2 py-1.5 text-[13px] font-medium">{a.ebook}</td>
      <td className="px-2 py-1.5 text-[13px]">{a.steps.join(" → ")}</td>
      <td className="px-2 py-1.5">
        <code className="text-xs">{a.schedule}</code>
      </td>
      <td data-numeric className="px-2 py-1.5 text-xs opacity-60">
        {a.next_run || "—"}
      </td>
      <td className="px-2 py-1.5">
        <input
          type="checkbox"
          checked={a.enabled}
          onChange={(e) =>
            update.mutate(
              { id: a.id, steps: a.steps, schedule: a.schedule, enabled: e.target.checked },
              { onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") },
            )
          }
          className="toggle toggle-sm"
          aria-label="Bật/tắt automation"
        />
      </td>
      <td data-numeric className="px-2 py-1.5 text-xs opacity-60">
        {a.last_run_at || "—"}
      </td>
      <td className="px-2 py-1.5">
        <Badge tone={OUTCOME_TONE[a.last_run_outcome] ?? "neutral"}>
          {OUTCOME_LABEL[a.last_run_outcome] ?? "—"}
        </Badge>
        {Object.keys(a.last_run_stats || {}).length > 0 ? (
          <p data-numeric className="mt-0.5 text-[11px] opacity-50">
            +{a.last_run_stats.crawled || 0} cào, +{a.last_run_stats.translated || 0} dịch,{" "}
            {a.last_run_stats.han_fixed || 0} Hán
          </p>
        ) : null}
      </td>
      <td className="px-2 py-1.5 text-right">
        <div className="flex justify-end gap-1.5">
          <Button
            size="sm"
            variant="primary"
            icon={<IconPlay size={12} />}
            loading={runNow.isPending}
            onClick={() =>
              runNow.mutate(a.id, {
                onSuccess: () => toast("Đã đưa automation vào hàng đợi."),
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              })
            }
          >
            Chạy ngay
          </Button>
          <Button size="sm" variant="danger" icon={<IconTrash size={12} />} onClick={onDelete} />
        </div>
      </td>
    </tr>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function AutomationPage() {
  const { data, isPending } = useAutomationOverview();
  const [addOpen, setAddOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Automation | null>(null);
  const del = useDeleteAutomation();

  return (
    <Page
      title="Tự động hóa"
      hint='Chuỗi bước chạy theo lịch cron hoặc bấm tay, đẩy qua hàng đợi job — job "automation" chiếm độc quyền crawl + dịch trong lúc chạy'
      actions={
        <Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setAddOpen(true)}>
          Thêm automation
        </Button>
      }
    >
      <Panel className="overflow-hidden">
        {isPending ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm opacity-60">
            <Spinner /> Đang tải
          </div>
        ) : !data || data.automations.length === 0 ? (
          <EmptyState title="Chưa có automation nào" hint='Bấm "Thêm automation" để tự động hóa crawl/dịch theo lịch.' />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[64rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  {["Ebook", "Các bước", "Lịch", "Chạy kế tiếp", "Bật", "Lần chạy cuối", "Kết quả", ""].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.automations.map((a) => (
                  <AutomationRow key={a.id} a={a} onDelete={() => setConfirmDelete(a)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {data ? <AddAutomationModal open={addOpen} onClose={() => setAddOpen(false)} ebooks={data.ebooks} steps={data.steps} /> : null}

      <ConfirmDialog
        open={confirmDelete !== null}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() =>
          confirmDelete &&
          del.mutate(confirmDelete.id, { onSuccess: () => setConfirmDelete(null) })
        }
        title="Xóa automation"
        body={`Xóa automation của ${confirmDelete?.ebook ?? ""}?`}
        confirmLabel="Xóa"
        destructive
        pending={del.isPending}
      />
    </Page>
  );
}
