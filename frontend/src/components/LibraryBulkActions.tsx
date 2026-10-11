import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { queueKey } from "@/lib/queue";
import {
  AUTOMATION_STEP_META,
  automationStepName,
  type Automation,
  type AutomationOverview,
} from "@/lib/automation";
import { Button } from "@/components/ui/Button";
import { Checkbox, Input } from "@/components/ui/Field";
import { Loading } from "@/components/ui/Loading";
import { Modal } from "@/components/ui/Modal";
import { EmptyState } from "@/components/ui/Panel";
import { SelectionBar } from "@/components/ui/SelectionBar";
import { useToast } from "@/components/ui/Toast";
import { IconBuild, IconPlay } from "@/components/icons";

export interface BulkBook {
  slug: string;
  title: string;
}

interface BulkResult extends BulkBook {
  ok: boolean;
  message: string;
}

type Mode = "automation" | "build" | null;

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Thanh thao tác hàng loạt của Thư viện: chạy workflow tự động / build EPUB
 * cho mọi truyện đã chọn. Mỗi truyện là một job riêng trong hàng đợi — truyện
 * lỗi (vd còn chương chưa dịch) không chặn các truyện còn lại, và được liệt kê
 * lại sau khi chạy.
 */
export function LibraryBulkActions({ books, onClear }: { books: BulkBook[]; onClear: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>(null);
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<BulkResult[] | null>(null);

  const [overview, setOverview] = useState<AutomationOverview | null>(null);
  const [overviewError, setOverviewError] = useState("");
  const [selectedSteps, setSelectedSteps] = useState<string[]>([]);
  const [crawlWorkers, setCrawlWorkers] = useState("4");
  const [translateWorkers, setTranslateWorkers] = useState("4");
  const [force, setForce] = useState(false);

  const loadOverview = async () => {
    setOverview(null);
    setOverviewError("");
    try {
      const data = await api.get<AutomationOverview>("/api/ui/automation");
      setOverview(data);
      setSelectedSteps(data.steps);
    } catch (err) {
      setOverviewError(errorText(err));
    }
  };

  const open = (next: Exclude<Mode, null>) => {
    setResults(null);
    setProgress(0);
    setForce(false);
    setMode(next);
    if (next === "automation") void loadOverview();
  };

  const close = () => {
    if (!pending) setMode(null);
  };

  /** Workflow đầu tiên của từng truyện — cùng mặc định với trang Tổng quan. */
  const workflowOf = (slug: string) => overview?.automations.find((automation) => automation.ebook === slug);
  const missing = overview ? books.filter((book) => !workflowOf(book.slug)) : [];

  const runAll = async (label: string, task: (book: BulkBook) => Promise<string>) => {
    setPending(true);
    setProgress(0);
    const next: BulkResult[] = [];
    // Tuần tự: tránh dội hàng chục request cùng lúc vào backend một tiến trình.
    for (const book of books) {
      try {
        next.push({ ...book, ok: true, message: await task(book) });
      } catch (err) {
        next.push({ ...book, ok: false, message: errorText(err) });
      }
      setProgress(next.length);
    }
    setPending(false);
    client.invalidateQueries({ queryKey: queueKey });
    client.invalidateQueries({ queryKey: ["automation"] });
    const failed = next.filter((item) => !item.ok).length;
    if (failed === 0) {
      setMode(null);
      onClear();
      toast(`Đã xếp ${label} cho ${num(next.length)} truyện vào hàng đợi.`);
    } else {
      setResults(next);
      toast(`${num(next.length - failed)} truyện đã vào hàng đợi, ${num(failed)} truyện lỗi.`, "error");
    }
  };

  const runAutomation = () => {
    const crawl = Number(crawlWorkers);
    const translate = Number(translateWorkers);
    if (missing.length) {
      if (!selectedSteps.length) return toast("Cần chọn ít nhất một bước.", "error");
      if (!Number.isInteger(crawl) || crawl < 1 || crawl > 64 || !Number.isInteger(translate) || translate < 1 || translate > 64) {
        return toast("Số luồng phải là số nguyên từ 1 đến 64.", "error");
      }
    }
    void runAll("workflow tự động", async (book) => {
      let automation = workflowOf(book.slug);
      const created = !automation;
      if (!automation) {
        automation = await api.post<Automation>("/api/ui/automation", {
          body: {
            ebook: book.slug,
            steps: selectedSteps,
            schedule: "manual",
            crawl_workers: crawl,
            translate_workers: translate,
          },
        });
      }
      try {
        await api.post<{ ok: boolean; job_id: string }>(`/api/ui/automation/${automation.id}/run-now`);
      } catch (err) {
        if (created) throw new Error(`Đã tạo workflow nhưng chưa chạy được: ${errorText(err)}`);
        throw err;
      }
      return created ? "Đã tạo workflow thủ công và xếp hàng." : "Đã xếp hàng.";
    });
  };

  const runBuild = () => {
    void runAll("Build EPUB", async (book) => {
      await api.post<{ ok: boolean; job_id: string }>(
        `/api/ui/ebooks/${encodeURIComponent(book.slug)}/build/confirm`,
        { body: { force } },
      );
      client.invalidateQueries({ queryKey: ["build-preview", book.slug] });
      return "Đã xếp hàng.";
    });
  };

  const failed = results?.filter((item) => !item.ok) ?? [];
  const progressLabel = pending ? ` (${num(progress)}/${num(books.length)})` : "";

  return (
    <>
      <SelectionBar count={books.length} noun="truyện đã chọn" onClear={onClear}>
        <Button size="sm" icon={<IconPlay size={14} />} onClick={() => open("automation")}>
          Chạy tự động
        </Button>
        <Button size="sm" icon={<IconBuild size={14} />} onClick={() => open("build")}>
          Build EPUB
        </Button>
      </SelectionBar>

      <Modal
        open={mode !== null}
        onClose={close}
        title={results ? "Kết quả thao tác hàng loạt" : mode === "build" ? "Build EPUB hàng loạt" : "Chạy tự động hàng loạt"}
        wide
        footer={
          results ? (
            <Button variant="primary" onClick={close}>Đóng</Button>
          ) : (
            <>
              <Button onClick={close} disabled={pending}>Hủy</Button>
              {mode === "build" ? (
                <Button variant="primary" icon={<IconBuild size={14} />} loading={pending} onClick={runBuild}>
                  Build {num(books.length)} truyện{progressLabel}
                </Button>
              ) : overview ? (
                <Button variant="primary" icon={<IconPlay size={14} />} loading={pending} onClick={runAutomation}>
                  Chạy {num(books.length)} truyện{progressLabel}
                </Button>
              ) : null}
            </>
          )
        }
      >
        {results ? (
          <div className="space-y-3 text-[13px]">
            <p>
              <span data-numeric className="font-semibold">{num(results.length - failed.length)}</span> truyện đã vào hàng đợi,{" "}
              <span data-numeric className="font-semibold text-error">{num(failed.length)}</span> truyện lỗi.
            </p>
            <BookList
              books={failed}
              note={(book) => <span className="break-words text-error">{book.message}</span>}
            />
          </div>
        ) : mode === "build" ? (
          <div className="space-y-3 text-[13px]">
            <p>Mỗi truyện được xếp một job Build EPUB riêng vào hàng đợi.</p>
            <BookList books={books} />
            <label className="flex cursor-pointer items-start gap-2 text-xs">
              <Checkbox className="mt-0.5" checked={force} disabled={pending} onChange={(event) => setForce(event.target.checked)} />
              <span>
                <span className="font-medium">Bỏ qua kiểm tra chương chưa dịch xong</span>
                <span className="block opacity-60">Khi tắt, truyện còn chương chưa có bản dịch hoàn chỉnh sẽ bị từ chối và được báo lại.</span>
              </span>
            </label>
          </div>
        ) : overviewError ? (
          <EmptyState
            title="Không đọc được workflow"
            hint={overviewError}
            action={<Button onClick={() => void loadOverview()}>Thử lại</Button>}
          />
        ) : !overview ? (
          <Loading label="Đang đọc workflow" />
        ) : (
          <div className="space-y-4 text-[13px]">
            <p>
              Truyện đã có workflow sẽ chạy workflow đó
              {missing.length ? <>; <span data-numeric className="font-semibold">{num(missing.length)}</span> truyện chưa có sẽ được tạo workflow thủ công theo các bước bên dưới rồi chạy ngay</> : null}.
            </p>
            <BookList
              books={books}
              note={(book) => {
                const automation = workflowOf(book.slug);
                return automation
                  ? <span className="opacity-60" title={automation.steps.map(automationStepName).join(" → ")}><span data-numeric>{automation.steps.length}</span> bước · {automation.schedule === "manual" ? "thủ công" : automation.schedule}</span>
                  : <span className="text-warning">Tạo workflow mới</span>;
              }}
            />
            {missing.length ? (
              <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
                <div className="overflow-hidden rounded-field border border-base-300">
                  {overview.steps.map((step) => (
                    <label key={step} className="flex cursor-pointer items-center gap-3 border-b border-base-300 px-3 py-2.5 last:border-b-0 hover:bg-base-200/40">
                      <Checkbox
                        checked={selectedSteps.includes(step)}
                        disabled={pending}
                        onChange={() => setSelectedSteps((current) => overview.steps.filter((item) => (item === step ? !current.includes(item) : current.includes(item))))}
                      />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-semibold">{automationStepName(step)}</span>
                        <span className="block text-[11px] opacity-55">{AUTOMATION_STEP_META[step]?.description}</span>
                      </span>
                    </label>
                  ))}
                </div>
                <div className="h-fit space-y-3 rounded-field border border-base-300 bg-base-200/35 p-3">
                  <p className="text-xs font-semibold">Tài nguyên</p>
                  <label className="block text-xs">
                    <span className="mb-1 block opacity-65">Luồng cào</span>
                    <Input value={crawlWorkers} onChange={(event) => setCrawlWorkers(event.target.value)} type="number" min={1} max={64} disabled={pending} />
                  </label>
                  <label className="block text-xs">
                    <span className="mb-1 block opacity-65">Luồng LLM dịch</span>
                    <Input value={translateWorkers} onChange={(event) => setTranslateWorkers(event.target.value)} type="number" min={1} max={64} disabled={pending} />
                  </label>
                  <p className="text-[11px] leading-relaxed opacity-55">Lịch mặc định: chỉ chạy thủ công. Có thể đổi cron tại trang Tự động.</p>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </Modal>
    </>
  );
}

function BookList<T extends BulkBook>({ books, note }: { books: T[]; note?: (book: T) => ReactNode }) {
  return (
    <ul className="scroll-slim max-h-56 overflow-y-auto rounded-field border border-base-300">
      {books.map((book) => (
        <li key={book.slug} className="flex items-start justify-between gap-3 border-b border-base-300 px-3 py-2 last:border-b-0">
          <span className="min-w-0">
            <span className="block truncate font-medium">{book.title || book.slug}</span>
            <span data-numeric className="block truncate text-[11px] opacity-45">{book.slug}</span>
          </span>
          {note ? <span className="max-w-[60%] shrink-0 text-right text-xs">{note(book)}</span> : null}
        </li>
      ))}
    </ul>
  );
}
