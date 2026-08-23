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
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { Checkbox, Field, Input, InputWithIcon, Select } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge, Dot, type Tone } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import {
  IconCheck,
  IconClock,
  IconClose,
  IconCopy,
  IconLog,
  IconMoveDown,
  IconMoveUp,
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

const PAGE_SIZE = 6;
type StatusFilter = "all" | "enabled" | "disabled" | "active" | "failed";
type ScheduleFilter = "all" | "scheduled" | "manual";

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
  copyFrom,
}: {
  open: boolean;
  onClose: () => void;
  ebooks: EbookOption[];
  steps: string[];
  automation: Automation | null;
  copyFrom: Automation | null;
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
    const source = automation ?? copyFrom;
    setEbook(source?.ebook ?? ebooks[0]?.slug ?? "");
    setSearch("");
    setSelectedSteps(source?.steps ?? steps);
    setCrawlWorkers(String(source?.crawl_workers ?? 4));
    setTranslateWorkers(String(source?.translate_workers ?? 4));
    setSchedule(source?.schedule ?? "manual");
  }, [open, automation, copyFrom, ebooks, steps]);

  useEffect(() => {
    if (open) validate.mutate(schedule);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schedule, open]);

  const filteredEbooks = ebooks.filter((e) => {
    const q = search.trim().toLowerCase();
    return !q || e.title.toLowerCase().includes(q) || e.slug.toLowerCase().includes(q);
  });
  const scheduleValid = validate.data?.valid !== false;
  const selectedEbook = ebooks.find((item) => item.slug === ebook);

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
    const parsedCrawlWorkers = Number(crawlWorkers);
    const parsedTranslateWorkers = Number(translateWorkers);
    if (
      !Number.isInteger(parsedCrawlWorkers) || parsedCrawlWorkers < 1 || parsedCrawlWorkers > 64 ||
      !Number.isInteger(parsedTranslateWorkers) || parsedTranslateWorkers < 1 || parsedTranslateWorkers > 64
    ) {
      toast("Số luồng phải là số nguyên từ 1 đến 64.", "error");
      return;
    }
    const input = {
      ebook,
      steps: selectedSteps,
      schedule: schedule.trim() || "manual",
      crawl_workers: parsedCrawlWorkers,
      translate_workers: parsedTranslateWorkers,
    };
    const options = {
      onSuccess: () => {
        toast(editing ? "Đã lưu tự động hóa." : copyFrom ? "Đã tạo bản sao tự động hóa." : "Đã tạo tự động hóa.");
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
      title={editing ? "Chỉnh sửa tự động hóa" : copyFrom ? "Sao chép tự động hóa" : "Thêm tự động hóa"}
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={create.isPending || update.isPending} onClick={submit}>
            {editing ? "Lưu thay đổi" : copyFrom ? "Tạo bản sao" : "Tạo tự động hóa"}
          </Button>
        </>
      }
    >
      <div className="grid gap-6 md:grid-cols-[minmax(0,1.2fr)_minmax(17rem,.8fr)]">
        <div className="space-y-6">
          <section aria-labelledby="automation-book-heading">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h3 id="automation-book-heading" className="text-sm font-semibold">Chọn truyện</h3>
              <span className="text-[11px] opacity-50">1 / 4</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,.8fr)]">
              <InputWithIcon
                icon={<IconSearch size={14} />}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Tìm tên hoặc mã truyện"
                className="w-full"
                disabled={editing}
                aria-label="Tìm truyện"
              />
              <Select
                value={ebook}
                onChange={(e) => setEbook(e.target.value)}
                className="w-full"
                disabled={editing}
                aria-label="Truyện áp dụng tự động hóa"
              >
                {filteredEbooks.length === 0
                  ? <option value="">Không có truyện phù hợp</option>
                  : filteredEbooks.map((e) => <option key={e.slug} value={e.slug}>{e.title}</option>)}
              </Select>
            </div>
            {editing ? <p className="mt-2 text-xs opacity-55">Truyện không thể đổi sau khi tạo tự động hóa.</p> : null}
          </section>

          <section aria-labelledby="automation-steps-heading">
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <h3 id="automation-steps-heading" className="text-sm font-semibold">Thiết kế pipeline</h3>
                <p className="mt-0.5 text-xs opacity-55">Chọn bước và sắp theo thứ tự thực thi.</p>
              </div>
              <span className="shrink-0 text-[11px] opacity-50">2 / 4 · {selectedSteps.length} bước</span>
            </div>
            <div className="overflow-hidden rounded-field border border-base-300">
              {orderedSteps.map((step) => {
                const selected = selectedSteps.includes(step);
                const index = selectedSteps.indexOf(step);
                return (
                  <div
                    key={step}
                    className={clsx(
                      "flex min-h-14 items-center gap-3 border-b border-base-300 px-3 py-2 last:border-b-0",
                      selected ? "bg-primary/5" : "bg-base-100",
                    )}
                  >
                    <span data-numeric className={clsx("w-5 text-center text-[11px]", selected ? "font-medium text-primary" : "opacity-35")}>
                      {selected ? index + 1 : "—"}
                    </span>
                    <Checkbox checked={selected} onChange={() => toggleStep(step)} aria-label={`${selected ? "Bỏ chọn" : "Chọn"} ${stepName(step)}`} />
                    <button type="button" onClick={() => toggleStep(step)} className="min-w-0 flex-1 text-left">
                      <span className={clsx("block text-[13px] font-semibold", !selected && "opacity-60")}>{stepName(step)}</span>
                      <span className="block truncate text-[11px] opacity-50">{STEP_META[step]?.description}</span>
                    </button>
                    {selected ? (
                      <div className="flex shrink-0 gap-1">
                        <Button size="sm" icon={<IconMoveUp size={12} />} onClick={() => moveStep(step, -1)} disabled={index === 0} aria-label={`Đưa ${stepName(step)} lên`} />
                        <Button size="sm" icon={<IconMoveDown size={12} />} onClick={() => moveStep(step, 1)} disabled={index === selectedSteps.length - 1} aria-label={`Đưa ${stepName(step)} xuống`} />
                      </div>
                    ) : <span className="text-[11px] opacity-35">Bỏ qua</span>}
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <aside className="space-y-6 md:border-l md:border-base-300 md:pl-6">
          <section aria-labelledby="automation-workers-heading">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h3 id="automation-workers-heading" className="text-sm font-semibold">Tài nguyên</h3>
              <span className="text-[11px] opacity-50">3 / 4</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Luồng cào">
                <Input type="number" min={1} max={64} value={crawlWorkers} onChange={(e) => setCrawlWorkers(e.target.value)} inputMode="numeric" />
              </Field>
              <Field label="Luồng LLM dịch">
                <Input type="number" min={1} max={64} value={translateWorkers} onChange={(e) => setTranslateWorkers(e.target.value)} inputMode="numeric" />
              </Field>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed opacity-50">Từ 1–64 luồng. Local MT tự quản lý tài nguyên riêng.</p>
          </section>

          <section aria-labelledby="automation-schedule-heading">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h3 id="automation-schedule-heading" className="text-sm font-semibold">Lịch chạy</h3>
              <span className="text-[11px] opacity-50">4 / 4</span>
            </div>
            <div className="mb-3 grid grid-cols-2 gap-1.5">
              {SCHEDULE_PRESETS.map((preset) => (
                <Button key={preset.cron} size="sm" variant={schedule === preset.cron ? "primary" : "neutral"} onClick={() => setSchedule(preset.cron)}>{preset.label}</Button>
              ))}
            </div>
            <Field
              label="Biểu thức cron"
              hint={scheduleValid ? "Thứ tự: phút, giờ, ngày, tháng, thứ." : "Cron chưa hợp lệ. Nhập đủ 5 trường hoặc chọn Chỉ chạy thủ công."}
            >
              <Input
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
                spellCheck={false}
                className={clsx("font-mono", !scheduleValid && "input-error")}
                aria-invalid={!scheduleValid}
              />
            </Field>
          </section>

          <div className="border-t border-base-300 pt-4 text-xs">
            <p className="font-semibold">Tóm tắt</p>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 opacity-65">
              <dt>Truyện</dt><dd className="truncate text-right font-medium">{selectedEbook?.title ?? "Chưa chọn"}</dd>
              <dt>Pipeline</dt><dd data-numeric className="text-right">{selectedSteps.length} bước</dd>
              <dt>Lịch</dt><dd className="truncate text-right font-mono text-[11px]">{schedule === "manual" ? "Thủ công" : schedule}</dd>
            </dl>
          </div>
        </aside>
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

function AutomationCard({ a, title, job, onEdit, onCopy, onDelete }: { a: Automation; title: string; job?: Job; onEdit: () => void; onCopy: () => void; onDelete: () => void }) {
  const update = useUpdateAutomation();
  const runNow = useRunAutomationNow();
  const { data: logData } = useJobLog(job ? job.id : null, job?.state === "running");
  const [logOpen, setLogOpen] = useState(false);
  const toast = useToast();
  const isActive = job?.state === "running" || job?.state === "pending";

  return (
    <article className="border-b border-base-300 last:border-b-0">
      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold tracking-tight">{title}</h2>
            {isActive ? <Badge tone="gold">{job?.state === "running" ? "Đang chạy" : "Đang chờ"}</Badge> : <Badge tone={OUTCOME_TONE[a.last_run_outcome] ?? "neutral"}>{OUTCOME_LABEL[a.last_run_outcome] ?? "Chưa chạy"}</Badge>}
            {!a.enabled ? <Badge tone="neutral">Đã tắt</Badge> : null}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs opacity-60">
            <span className="flex items-center gap-1.5"><IconClock size={13} /> <span className={a.schedule === "manual" ? "" : "font-mono text-[11px]"}>{a.schedule === "manual" ? "Chạy thủ công" : a.schedule}</span></span>
            <span><span className="opacity-70">Lần cuối</span> <span data-numeric>{a.last_run_at || "—"}</span></span>
            {a.next_run ? <span><span className="opacity-70">Kế tiếp</span> <span data-numeric>{a.next_run}</span></span> : null}
            <span data-numeric>{a.steps.length} bước · {a.crawl_workers} luồng cào · {a.translate_workers} luồng dịch</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 md:justify-end">
          <label className="mr-1 flex min-h-8 items-center gap-2 rounded-field px-2 text-xs hover:bg-base-200">
            <span className="opacity-60">Kích hoạt</span>
            <input
              type="checkbox"
              checked={a.enabled}
              disabled={update.isPending}
              onChange={(e) => update.mutate(
                { id: a.id, ebook: a.ebook, steps: a.steps, schedule: a.schedule, enabled: e.target.checked, crawl_workers: a.crawl_workers, translate_workers: a.translate_workers },
                { onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") },
              )}
              className="toggle toggle-sm"
              aria-label={`${a.enabled ? "Tắt" : "Bật"} tự động hóa ${title}`}
            />
          </label>
          <Button size="sm" icon={<IconLog size={13} />} onClick={() => setLogOpen(true)}>Nhật ký</Button>
          <Button size="sm" icon={<IconNoteAdd size={13} />} onClick={onEdit}>Chỉnh sửa</Button>
          <Button size="sm" icon={<IconCopy size={13} />} onClick={onCopy}>Sao chép</Button>
          <Button size="sm" variant="primary" icon={<IconPlay size={13} />} loading={runNow.isPending} disabled={isActive} onClick={() => runNow.mutate(a.id, { onSuccess: () => toast("Đã đưa tự động hóa vào hàng đợi."), onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") })}>Chạy ngay</Button>
          <Button size="sm" variant="danger" icon={<IconTrash size={13} />} onClick={onDelete} aria-label={`Xóa tự động hóa ${title}`} />
        </div>
      </div>

      <div className="border-t border-base-300 bg-base-200/35 px-4 py-4 md:px-5">
        <div className="scroll-slim overflow-x-auto pb-1"><Pipeline automation={a} job={job} logs={logData?.log ?? []} /></div>
      </div>

      {(a.last_run_error || Object.keys(a.last_run_stats || {}).length > 0) ? (
        <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-base-300 px-4 py-3 text-xs md:px-5">
          <span className="opacity-60"><span data-numeric className="font-medium text-base-content">+{a.last_run_stats?.crawled || 0}</span> chương cào</span>
          <span className="opacity-60"><span data-numeric className="font-medium text-base-content">+{a.last_run_stats?.translated || 0}</span> chương dịch</span>
          <span className="opacity-60"><span data-numeric className="font-medium text-base-content">{a.last_run_stats?.han_fixed || 0}</span> từ Hán đã sửa</span>
          {a.last_run_error ? <span className="basis-full text-error md:basis-auto">{a.last_run_error}</span> : null}
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
  const [copyFrom, setCopyFrom] = useState<Automation | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Automation | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [scheduleFilter, setScheduleFilter] = useState<ScheduleFilter>("all");
  const [page, setPage] = useState(1);
  const del = useDeleteAutomation();
  const jobs = useMemo(() => queue ? [...queue.running, ...Object.values(queue.pending).flat(), ...queue.history] : [], [queue]);
  const titles = useMemo(() => new Map(data?.ebooks.map((ebook) => [ebook.slug, ebook.title]) ?? []), [data]);
  const activeCount = useMemo(
    () => data?.automations.filter((automation) => {
      const job = automationJob(automation, jobs);
      return job?.state === "running" || job?.state === "pending";
    }).length ?? 0,
    [data, jobs],
  );
  const enabledCount = data?.automations.filter((automation) => automation.enabled).length ?? 0;
  const filteredAutomations = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("vi");
    return (data?.automations ?? []).filter((automation) => {
      const title = titles.get(automation.ebook) ?? automation.ebook;
      const job = automationJob(automation, jobs);
      const active = job?.state === "running" || job?.state === "pending";
      const matchesSearch = !query || title.toLocaleLowerCase("vi").includes(query) || automation.ebook.toLowerCase().includes(query);
      const matchesStatus = statusFilter === "all" ||
        (statusFilter === "enabled" && automation.enabled) ||
        (statusFilter === "disabled" && !automation.enabled) ||
        (statusFilter === "active" && active) ||
        (statusFilter === "failed" && automation.last_run_outcome === "failure");
      const matchesSchedule = scheduleFilter === "all" ||
        (scheduleFilter === "manual" && automation.schedule === "manual") ||
        (scheduleFilter === "scheduled" && automation.schedule !== "manual");
      return matchesSearch && matchesStatus && matchesSchedule;
    });
  }, [data, jobs, scheduleFilter, search, statusFilter, titles]);
  const pageCount = Math.max(1, Math.ceil(filteredAutomations.length / PAGE_SIZE));
  const visibleAutomations = filteredAutomations.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const filtersActive = search.trim() !== "" || statusFilter !== "all" || scheduleFilter !== "all";

  useEffect(() => setPage(1), [search, statusFilter, scheduleFilter]);
  useEffect(() => setPage((current) => Math.min(current, pageCount)), [pageCount]);

  const closeForm = () => { setFormOpen(false); setEditing(null); setCopyFrom(null); };
  const clearFilters = () => { setSearch(""); setStatusFilter("all"); setScheduleFilter("all"); };

  return (
    <Page
      title="Tự động hóa"
      hint={data ? <><span data-numeric>{enabledCount}</span> đang bật · <span data-numeric>{activeCount}</span> đang chạy hoặc chờ · <span data-numeric>{data.automations.length}</span> pipeline</> : "Đang đọc cấu hình và lịch chạy"}
      actions={<Button variant="primary" icon={<IconPlus size={14} />} onClick={() => { setEditing(null); setCopyFrom(null); setFormOpen(true); }}>Thêm tự động hóa</Button>}
    >
      {data?.automations.length ? (
        <Panel className="mb-3 p-3">
          <div className="grid gap-2 md:grid-cols-[minmax(14rem,1fr)_11rem_11rem_auto]">
            <InputWithIcon
              icon={<IconSearch size={14} />}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Tìm theo tên hoặc mã truyện"
              className="w-full"
              aria-label="Tìm tự động hóa"
            />
            <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)} className="w-full" aria-label="Lọc theo trạng thái">
              <option value="all">Mọi trạng thái</option>
              <option value="enabled">Đang bật</option>
              <option value="disabled">Đã tắt</option>
              <option value="active">Đang chạy hoặc chờ</option>
              <option value="failed">Lần cuối có lỗi</option>
            </Select>
            <Select value={scheduleFilter} onChange={(event) => setScheduleFilter(event.target.value as ScheduleFilter)} className="w-full" aria-label="Lọc theo lịch chạy">
              <option value="all">Mọi lịch chạy</option>
              <option value="scheduled">Có lịch</option>
              <option value="manual">Chỉ thủ công</option>
            </Select>
            <Button onClick={clearFilters} disabled={!filtersActive}>Xóa bộ lọc</Button>
          </div>
        </Panel>
      ) : null}

      <Panel className="overflow-hidden">
        {!isPending && data?.automations.length ? <PanelHeader title="Pipeline tự động" hint={`Hiển thị ${visibleAutomations.length} trong ${filteredAutomations.length} kết quả.`} /> : null}
        {isPending ? <SkeletonTable rows={3} cols={4} /> : !data?.automations.length ? (
          <EmptyState title="Chưa có tự động hóa" hint="Tạo pipeline đầu tiên để cào, dịch và xuất sách theo lịch." action={<Button variant="primary" icon={<IconPlus size={14} />} onClick={() => setFormOpen(true)}>Thêm tự động hóa</Button>} />
        ) : visibleAutomations.length === 0 ? (
          <EmptyState title="Không tìm thấy tự động hóa" hint="Thử từ khóa khác hoặc xóa bớt bộ lọc." action={<Button onClick={clearFilters}>Xóa bộ lọc</Button>} />
        ) : visibleAutomations.map((a) => (
          <AutomationCard
            key={a.id}
            a={a}
            title={titles.get(a.ebook) ?? a.ebook}
            job={automationJob(a, jobs)}
            onEdit={() => { setCopyFrom(null); setEditing(a); setFormOpen(true); }}
            onCopy={() => { setEditing(null); setCopyFrom(a); setFormOpen(true); }}
            onDelete={() => setConfirmDelete(a)}
          />
        ))}
        {!isPending && filteredAutomations.length > PAGE_SIZE ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 px-4 py-3 text-xs md:px-5">
            <span className="opacity-60">Trang <span data-numeric>{page}</span> / <span data-numeric>{pageCount}</span></span>
            <div className="flex gap-1.5">
              <Button size="sm" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Trang trước</Button>
              <Button size="sm" disabled={page === pageCount} onClick={() => setPage((current) => current + 1)}>Trang sau</Button>
            </div>
          </div>
        ) : null}
      </Panel>

      {data ? <FormModal open={formOpen} onClose={closeForm} ebooks={data.ebooks} steps={data.steps} automation={editing} copyFrom={copyFrom} /> : null}
      <ConfirmDialog open={confirmDelete !== null} onCancel={() => setConfirmDelete(null)} onConfirm={() => confirmDelete && del.mutate(confirmDelete.id, { onSuccess: () => setConfirmDelete(null) })} title="Xóa tự động hóa" body={`Xóa tự động hóa của “${titles.get(confirmDelete?.ebook ?? "") ?? ""}”?`} confirmLabel="Xóa" destructive pending={del.isPending} />
    </Page>
  );
}
