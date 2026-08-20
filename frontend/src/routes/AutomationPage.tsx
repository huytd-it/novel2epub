import { useEffect, useMemo, useRef, useState } from "react";
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
  type EbookOption,
} from "@/lib/automation";
import { useJobLog, useQueue, type Job } from "@/lib/queue";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { Input, InputWithIcon } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge, Dot, type Tone } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import {
  IconCheck,
  IconClock,
  IconClose,
  IconLog,
  IconNoteAdd,
  IconPlay,
  IconPlus,
  IconSearch,
  IconTrash,
} from "@/components/icons";

const OUTCOME_TONE: Record<string, Tone> = {
  success: "celadon",
  failure: "vermilion",
  partial: "gold",
};
const OUTCOME_LABEL: Record<string, string> = {
  success: "Thành công",
  failure: "Có lỗi",
  partial: "Một phần",
};

const STEP_META: Record<string, { name: string; description: string }> = {
  "fetch-toc": { name: "Cập nhật mục lục", description: "Lấy danh sách chương mới từ nguồn" },
  "crawl-new": { name: "Cào chương mới", description: "Tải nội dung gốc của các chương còn thiếu" },
  "translate-local-mt": { name: "Dịch Local MT", description: "Dịch nhanh bằng mô hình chạy cục bộ" },
  "translate-pending": { name: "LLM dịch", description: "Dịch các chương đang chờ bằng LLM" },
  "llm-edit": { name: "LLM biên tập", description: "Tạo bản nháp biên tập từ bản Local MT" },
  "cleanup-han": { name: "Dọn từ Hán", description: "Rà soát và làm sạch từ Hán còn sót" },
  build: { name: "Đóng gói EPUB", description: "Tạo lại tệp EPUB hoàn chỉnh" },
  "publish-reader": { name: "Đăng Reader", description: "Đồng bộ bản mới lên Reader" },
};

const SCHEDULE_PRESETS = [
  { label: "15 phút", cron: "*/15 * * * *" },
  { label: "30 phút", cron: "*/30 * * * *" },
  { label: "Mỗi giờ", cron: "0 * * * *" },
  { label: "Hàng ngày · 03:00", cron: "0 3 * * *" },
  { label: "Chủ nhật · 03:00", cron: "0 3 * * 0" },
  { label: "Chỉ chạy thủ công", cron: "manual" },
];

function stepName(step: string) {
  return STEP_META[step]?.name ?? step;
}

function automationJob(a: Automation, jobs: Job[]): Job | undefined {
  return jobs.find((job) => job.automation_id === a.id) ??
    jobs.find((job) => job.step === "automation" && job.ebook === a.ebook);
}

function FormModal({
  open,
  onClose,
  ebooks,
  steps,
  automation,
}: {
  open: boolean;
  onClose: () => void;
  ebooks: EbookOption[];
  steps: string[];
  automation: Automation | null;
}) {
  const [ebook, setEbook] = useState("");
  const [search, setSearch] = useState("");
  const [selectedSteps, setSelectedSteps] = useState<string[]>([]);
  const [crawlWorkers, setCrawlWorkers] = useState("4");
  const [translateWorkers, setTranslateWorkers] = useState("4");
  const [schedule, setSchedule] = useState("manual");
  const create = useCreateAutomation();
  const update = useUpdateAutomation();
  const validate = useValidateSchedule();
  const toast = useToast();
  const editing = automation !== null;

  useEffect(() => {
    if (!open) return;
    setEbook(automation?.ebook ?? ebooks[0]?.slug ?? "");
    setSearch("");
    setSelectedSteps(automation?.steps ?? steps);
    setCrawlWorkers(String(automation?.crawl_workers ?? 4));
    setTranslateWorkers(String(automation?.translate_workers ?? 4));
    setSchedule(automation?.schedule ?? "manual");
  }, [open, automation, ebooks, steps]);

  useEffect(() => {
    if (open) validate.mutate(schedule);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schedule, open]);

  const filteredEbooks = ebooks.filter((e) => {
    const q = search.trim().toLowerCase();
    return !q || e.title.toLowerCase().includes(q);
  });

  const toggleStep = (step: string) =>
    setSelectedSteps((current) =>
      current.includes(step) ? current.filter((item) => item !== step) : [...current, step],
    );

  const moveStep = (step: string, direction: -1 | 1) => {
    setSelectedSteps((current) => {
      const index = current.indexOf(step);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const submit = () => {
    const hasEbook = ebooks.some((e) => e.slug === ebook);
    if (!hasEbook || selectedSteps.length === 0) {
      toast(!hasEbook ? "Chọn truyện từ danh sách." : "Cần chọn ít nhất một bước.", "error");
      return;
    }
    if (validate.data && !validate.data.valid) {
      toast("Lịch chạy không hợp lệ.", "error");
      return;
    }
    const input = {
      ebook,
      steps: selectedSteps,
      schedule: schedule.trim() || "manual",
      crawl_workers: Number(crawlWorkers) || 4,
      translate_workers: Number(translateWorkers) || 4,
    };
    const options = {
      onSuccess: () => {
        toast(editing ? "Đã lưu tự động hóa." : "Đã tạo tự động hóa.");
        onClose();
      },
      onError: (err: Error) => toast(err.message, "error" as const),
    };
    if (automation) update.mutate({ ...input, id: automation.id, enabled: automation.enabled }, options);
    else create.mutate(input, options);
  };

  const orderedSteps = [
    ...selectedSteps,
    ...steps.filter((step) => !selectedSteps.includes(step)),
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Chỉnh sửa tự động hóa" : "Thêm tự động hóa"}
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={create.isPending || update.isPending} onClick={submit}>
            {editing ? "Lưu thay đổi" : "Tạo tự động hóa"}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1.15fr)_minmax(16rem,.85fr)]">
        <div className="space-y-5">
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">1. Chọn truyện</legend>
            <InputWithIcon
              icon={<IconSearch size={14} />}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm theo tên truyện"
              className="mb-2 w-full"
              disabled={editing}
            />
            <select
              value={ebook}
              onChange={(e) => setEbook(e.target.value)}
              className="select w-full"
              disabled={editing}
            >
              {filteredEbooks.length === 0
                ? <option value="">Không có truyện nào khớp</option>
                : filteredEbooks.map((e) => <option key={e.slug} value={e.slug}>{e.title}</option>)}
            </select>
          </fieldset>

          <fieldset>
            <legend className="mb-1 text-sm font-semibold">2. Chọn và sắp xếp các bước</legend>
            <p className="mb-3 text-xs opacity-55">Các bước chạy lần lượt từ trên xuống. Dùng mũi tên để đổi thứ tự.</p>
            <div className="space-y-2">
              {orderedSteps.map((step) => {
                const selected = selectedSteps.includes(step);
                const index = selectedSteps.indexOf(step);
                return (
                  <div key={step} className={clsx("flex items-center gap-3 rounded-field border px-3 py-2", selected ? "border-primary/40 bg-primary/5" : "border-base-300 opacity-60")}>
                    <input type="checkbox" checked={selected} onChange={() => toggleStep(step)} className="checkbox checkbox-sm" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold">{stepName(step)}</p>
                      <p className="truncate text-[11px] opacity-55">{STEP_META[step]?.description}</p>
                    </div>
                    {selected ? (
                      <div className="flex gap-1">
                        <Button size="sm" onClick={() => moveStep(step, -1)} disabled={index === 0} aria-label={`Đưa ${stepName(step)} lên`}>↑</Button>
                        <Button size="sm" onClick={() => moveStep(step, 1)} disabled={index === selectedSteps.length - 1} aria-label={`Đưa ${stepName(step)} xuống`}>↓</Button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </fieldset>
        </div>

        <div className="space-y-5">
          <fieldset>
            <legend className="mb-2 text-sm font-semibold">3. Thiết lập tài nguyên</legend>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs font-medium">Luồng cào
                <Input type="number" min={1} max={64} value={crawlWorkers} onChange={(e) => setCrawlWorkers(e.target.value)} className="mt-1 w-full" />
              </label>
              <label className="text-xs font-medium">Luồng LLM dịch
                <Input type="number" min={1} max={64} value={translateWorkers} onChange={(e) => setTranslateWorkers(e.target.value)} className="mt-1 w-full" />
              </label>
            </div>
            <p className="mt-2 text-[11px] opacity-50">Local MT tự quản lý tài nguyên và không dùng số luồng LLM.</p>
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm font-semibold">4. Đặt lịch chạy</legend>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {SCHEDULE_PRESETS.map((preset) => (
                <Button key={preset.cron} size="sm" variant={schedule === preset.cron ? "primary" : "neutral"} onClick={() => setSchedule(preset.cron)}>{preset.label}</Button>
              ))}
            </div>
            <Input value={schedule} onChange={(e) => setSchedule(e.target.value)} spellCheck={false} className="w-full font-mono" />
            <p className={clsx("mt-2 text-xs", validate.data?.valid === false ? "text-error" : "opacity-50")}>
              {validate.data?.valid === false ? "Cron không hợp lệ. Cần đủ 5 trường." : "Thứ tự cron: phút, giờ, ngày, tháng, thứ."}
            </p>
          </fieldset>
        </div>
      </div>
    </Modal>
  );
}

function parseStepState(step: string, steps: string[], job: Job | undefined, logs: string[]) {
  if (!job || job.state === "pending") return "idle";
  const failed = logs.some((line) => line.includes(`[automation:step:failed] ${step}`));
  const done = logs.some((line) => line.includes(`[automation:step:done] ${step}`));
  const started = logs.some((line) => line.includes(`[automation:step:start] ${step}`));
  if (failed) return "failed";
  if (done) return "done";
  if (started && job.state === "running") return "running";
  if (job.state === "done" && steps.includes(step)) return "done";
  return "idle";
}

function Pipeline({ automation, job, logs }: { automation: Automation; job?: Job; logs: string[] }) {
  return (
    <ol className="flex min-w-max items-start">
      {automation.steps.map((step, index) => {
        const state = parseStepState(step, automation.steps, job, logs);
        return (
          <li key={`${step}-${index}`} className="flex items-start">
            <div className="w-28 text-center">
              <div className={clsx("mx-auto flex size-6 items-center justify-center rounded-full border text-xs", state === "done" && "border-success bg-success text-success-content", state === "running" && "border-warning bg-warning/15 text-warning", state === "failed" && "border-error bg-error text-error-content", state === "idle" && "border-base-300 bg-base-100 opacity-55")}>
                {state === "done" ? <IconCheck size={13} /> : state === "failed" ? <IconClose size={13} /> : state === "running" ? <Dot tone="gold" pulse /> : index + 1}
              </div>
              <p className={clsx("mt-1 text-[11px] leading-tight font-medium", state === "idle" && "opacity-50")}>{stepName(step)}</p>
            </div>
            {index < automation.steps.length - 1 ? <span className={clsx("mt-3 -mx-4 h-px w-8", state === "done" ? "bg-success" : "bg-base-300")} /> : null}
          </li>
        );
      })}
    </ol>
  );
}

function LogModal({ automation, job, open, onClose }: { automation: Automation; job?: Job; open: boolean; onClose: () => void }) {
  const { data, isPending } = useJobLog(open && job ? job.id : null, job?.state === "running");
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [data?.log]);
  return (
    <Modal open={open} onClose={onClose} title={`Nhật ký · ${automation.ebook}`} wide footer={<Button onClick={onClose}>Đóng</Button>}>
      {!job ? <EmptyState title="Chưa có lần chạy" hint="Chạy tự động hóa để bắt đầu ghi nhật ký riêng." /> : isPending ? <Loading label="Đang đọc nhật ký" /> : (
        <div ref={boxRef} className="scroll-slim max-h-[55vh] overflow-auto bg-base-200 px-3 py-2">
          {(data?.log ?? []).length === 0 ? <p className="py-8 text-center text-sm opacity-50">Job chưa ghi dòng log nào.</p> : (data?.log ?? []).map((line, index) => (
            <pre key={index} className={clsx("m-0 text-[12px] leading-[1.55] break-words whitespace-pre-wrap", /ERROR|CRITICAL|Traceback|failed|Lỗi/.test(line) ? "text-error" : /automation:step:(start|done)/.test(line) ? "font-semibold text-primary" : "opacity-65")}>{line}</pre>
          ))}
        </div>
      )}
    </Modal>
  );
}

function AutomationCard({ a, title, job, onEdit, onDelete }: { a: Automation; title: string; job?: Job; onEdit: () => void; onDelete: () => void }) {
  const update = useUpdateAutomation();
  const runNow = useRunAutomationNow();
  const { data: logData } = useJobLog(job ? job.id : null, job?.state === "running");
  const [logOpen, setLogOpen] = useState(false);
  const toast = useToast();
  const isActive = job?.state === "running" || job?.state === "pending";

  return (
    <article className="border-b border-base-300 p-4 last:border-b-0 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {isActive ? <Badge tone="gold">{job?.state === "running" ? "Đang chạy" : "Đang chờ"}</Badge> : <Badge tone={OUTCOME_TONE[a.last_run_outcome] ?? "neutral"}>{OUTCOME_LABEL[a.last_run_outcome] ?? "Chưa chạy"}</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs opacity-55">
            <span className="flex items-center gap-1"><IconClock size={13} /> {a.schedule === "manual" ? "Chạy thủ công" : a.schedule}</span>
            <span>Lần cuối: {a.last_run_at || "—"}</span>
            {a.next_run ? <span>Kế tiếp: {a.next_run}</span> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs">
            <span className="opacity-55">{a.enabled ? "Đang bật" : "Đang tắt"}</span>
            <input type="checkbox" checked={a.enabled} onChange={(e) => update.mutate({ id: a.id, ebook: a.ebook, steps: a.steps, schedule: a.schedule, enabled: e.target.checked, crawl_workers: a.crawl_workers, translate_workers: a.translate_workers })} className="toggle toggle-sm" />
          </label>
          <Button size="sm" icon={<IconLog size={13} />} onClick={() => setLogOpen(true)}>Nhật ký</Button>
          <Button size="sm" icon={<IconNoteAdd size={13} />} onClick={onEdit}>Sửa</Button>
          <Button size="sm" variant="primary" icon={<IconPlay size={13} />} loading={runNow.isPending} disabled={isActive} onClick={() => runNow.mutate(a.id, { onSuccess: () => toast("Đã đưa tự động hóa vào hàng đợi."), onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") })}>Chạy ngay</Button>
          <Button size="sm" variant="danger" icon={<IconTrash size={13} />} onClick={onDelete} aria-label={`Xóa tự động hóa ${title}`} />
        </div>
      </div>

      <div className="mt-5 overflow-x-auto pb-1"><Pipeline automation={a} job={job} logs={logData?.log ?? []} /></div>

      {(a.last_run_error || Object.keys(a.last_run_stats || {}).length > 0) ? (
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t border-base-300 pt-3 text-xs opacity-60">
          <span>+{a.last_run_stats?.crawled || 0} chương cào</span>
          <span>+{a.last_run_stats?.translated || 0} chương dịch</span>
          <span>{a.last_run_stats?.han_fixed || 0} từ Hán đã sửa</span>
          {a.last_run_error ? <span className="text-error">{a.last_run_error}</span> : null}
        </div>
      ) : null}
      <LogModal automation={a} job={job} open={logOpen} onClose={() => setLogOpen(false)} />
    </article>
  );
}

export function AutomationPage() {
  const { data, isPending } = useAutomationOverview();
  const { data: queue } = useQueue();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Automation | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Automation | null>(null);
  const del = useDeleteAutomation();
  const jobs = useMemo(() => queue ? [...queue.running, ...Object.values(queue.pending).flat(), ...queue.history] : [], [queue]);
  const titles = useMemo(() => new Map(data?.ebooks.map((ebook) => [ebook.slug, ebook.title]) ?? []), [data]);

  const closeForm = () => { setFormOpen(false); setEditing(null); };

  return (
    <Page
      title="Tự động hóa"
      hint="Thiết lập pipeline theo lịch, theo dõi từng bước và xem nhật ký riêng cho mỗi lần chạy."
      actions={<Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setFormOpen(true)}>Thêm tự động hóa</Button>}
    >
      <Panel className="overflow-hidden">
        {isPending ? <SkeletonTable rows={3} cols={4} /> : !data?.automations.length ? (
          <EmptyState title="Chưa có tự động hóa" hint="Tạo pipeline đầu tiên để cào, dịch và xuất sách theo lịch." action={<Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setFormOpen(true)}>Thêm tự động hóa</Button>} />
        ) : data.automations.map((a) => (
          <AutomationCard key={a.id} a={a} title={titles.get(a.ebook) ?? a.ebook} job={automationJob(a, jobs)} onEdit={() => { setEditing(a); setFormOpen(true); }} onDelete={() => setConfirmDelete(a)} />
        ))}
      </Panel>

      {data ? <FormModal open={formOpen} onClose={closeForm} ebooks={data.ebooks} steps={data.steps} automation={editing} /> : null}
      <ConfirmDialog open={confirmDelete !== null} onCancel={() => setConfirmDelete(null)} onConfirm={() => confirmDelete && del.mutate(confirmDelete.id, { onSuccess: () => setConfirmDelete(null) })} title="Xóa tự động hóa" body={`Xóa tự động hóa của “${titles.get(confirmDelete?.ebook ?? "") ?? ""}”?`} confirmLabel="Xóa" destructive pending={del.isPending} />
    </Page>
  );
}
