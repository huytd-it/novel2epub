import { useNavigate } from "react-router";

import { Page } from "@/app/Shell";
import { bytes, num } from "@/lib/format";
import { useDashboard, type AutomationStatus, type DashboardRow } from "@/lib/dashboard";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Button";
import { Badge, Dot } from "@/components/ui/Badge";

/* ── Donut SVG thuần — không cần thư viện chart ─────────────────────── */

function Donut({ translated, rawOnly, remaining }: { translated: number; rawOnly: number; remaining: number }) {
  const total = translated + rawOnly + remaining || 1;
  const r = 60;
  const c = 2 * Math.PI * r;
  const segs = [
    { value: translated, color: "var(--color-success)" },
    { value: rawOnly, color: "var(--color-info)" },
    { value: remaining, color: "var(--color-base-300)" },
  ];
  let offset = 0;
  return (
    <svg viewBox="0 0 140 140" className="size-36 md:size-40" role="img" aria-label="Tiến độ tổng">
      <g transform="rotate(-90 70 70)">
        {segs.map((s, i) => {
          const frac = s.value / total;
          const dash = frac * c;
          const el = (
            <circle
              key={i}
              cx={70}
              cy={70}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth={16}
              strokeDasharray={`${dash} ${c - dash}`}
              strokeDashoffset={-offset}
            />
          );
          offset += dash;
          return el;
        })}
      </g>
      <text x="70" y="66" textAnchor="middle" className="fill-current text-[22px] font-semibold">
        {Math.round((translated / total) * 100)}%
      </text>
      <text x="70" y="84" textAnchor="middle" className="fill-current text-[10px] opacity-50">
        đã dịch
      </text>
    </svg>
  );
}

/* ── Ô số liệu tổng ──────────────────────────────────────────────────── */

function StatCard({ label, value, tone }: { label: string; value: string; tone?: "error" | "info" }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-100 p-3">
      <p className="text-[10px] tracking-[0.1em] uppercase opacity-50">{label}</p>
      <p
        data-numeric
        className={
          "mt-0.5 text-2xl font-bold " +
          (tone === "error" ? "text-error" : tone === "info" ? "text-info" : "")
        }
      >
        {value}
      </p>
    </div>
  );
}

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

function AutomationLine({ a }: { a: AutomationStatus }) {
  const stats = a.last_run_stats || {};
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <code className="rounded bg-base-200 px-1.5 py-0.5">
        {a.steps.join(" → ")} ({a.schedule}
        {a.enabled ? "" : ", tắt"})
      </code>
      <Badge tone={OUTCOME_TONE[a.last_run_outcome] ?? "neutral"}>
        {OUTCOME_LABEL[a.last_run_outcome] ?? "chưa chạy"}
      </Badge>
      {Object.keys(stats).length > 0 ? (
        <span data-numeric className="opacity-50">
          +{stats.crawled || 0} cào, +{stats.translated || 0} dịch, {stats.han_fixed || 0} Hán
        </span>
      ) : null}
    </div>
  );
}

function EbookRow({ row }: { row: DashboardRow }) {
  const navigate = useNavigate();
  const hasError = row.automations.some((a) => a.last_run_error);
  const p = row.progress;

  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <button
          type="button"
          onClick={() => navigate(`/ebooks/${row.slug}`)}
          className="font-display text-[15px] font-semibold hover:text-primary"
        >
          {row.title}
        </button>
        {hasError ? <Badge tone="vermilion">có lỗi</Badge> : null}
      </div>

      <div className="space-y-2">
        <div className="grid grid-cols-[3rem_1fr_7rem] items-center gap-2 text-[11px]">
          <span className="opacity-50">Cào</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-base-200">
            <div className="h-full rounded-full bg-info" style={{ width: `${p.raw_pct}%` }} />
          </div>
          <span data-numeric className="text-right opacity-60">
            {num(p.raw_count)}/{num(p.total)} ({p.raw_pct}%)
          </span>
        </div>
        <div className="grid grid-cols-[3rem_1fr_7rem] items-center gap-2 text-[11px]">
          <span className="opacity-50">Dịch</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-base-200">
            <div className="h-full rounded-full bg-success" style={{ width: `${p.translated_pct}%` }} />
          </div>
          <span data-numeric className="text-right opacity-60">
            {num(p.translated_count)}/{num(p.total)} ({p.translated_pct}%)
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-60">
        {row.crawl_problems ? (
          <span className="flex items-center gap-1">
            <Dot tone="vermilion" /> {num(row.crawl_problems)} chương lỗi cào
          </span>
        ) : null}
        {row.han_fixed ? <span data-numeric>{num(row.han_fixed)} chỗ Hán đã sửa</span> : null}
        <span data-numeric>{bytes(row.disk_total)}</span>
        {row.cost_summary ? (
          <span data-numeric>${row.cost_summary.total_cost_usd.toFixed(4)}</span>
        ) : null}
      </div>

      {row.automations.length > 0 ? (
        <div className="mt-2.5 space-y-1">
          {row.automations.map((a) => (
            <AutomationLine key={a.id} a={a} />
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

export function DashboardPage() {
  const { data, isPending } = useDashboard();

  if (isPending || !data) {
    return (
      <Page title="Bảng điều khiển">
        <div className="flex items-center justify-center gap-2 py-16 text-sm opacity-60">
          <Spinner /> Đang tải
        </div>
      </Page>
    );
  }

  const { summary, rows } = data;
  const rawOnly = Math.max(summary.raw_count - summary.translated_count, 0);
  const remaining = Math.max(summary.total_chapters - summary.translated_count - rawOnly, 0);

  return (
    <Page title="Bảng điều khiển" hint="Tiến độ, lỗi automation, chi phí dịch và dung lượng mọi truyện — tự làm mới mỗi 4 giây">
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Truyện" value={num(summary.ebook_count)} />
        <StatCard label="Tổng chương" value={num(summary.total_chapters)} />
        <StatCard label="Đang lỗi" value={num(summary.error_count)} tone={summary.error_count ? "error" : undefined} />
        <StatCard label="Job đang chạy" value={num(summary.running_jobs)} tone={summary.running_jobs ? "info" : undefined} />
      </div>

      <Panel className="mb-4 p-4 md:p-5">
        <div className="grid grid-cols-1 items-center gap-4 md:grid-cols-[180px_1fr] md:gap-6">
          <div className="flex justify-center md:justify-start">
            <Donut translated={summary.translated_count} rawOnly={rawOnly} remaining={remaining} />
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="mb-0.5 text-xs tracking-wide uppercase opacity-50">Đã dịch</p>
              <p data-numeric className="text-xl font-semibold text-success">
                {num(summary.translated_count)}
              </p>
              <p data-numeric className="text-xs opacity-50">
                {summary.translated_pct}%
              </p>
            </div>
            <div>
              <p className="mb-0.5 text-xs tracking-wide uppercase opacity-50">Đã cào (chưa dịch)</p>
              <p data-numeric className="text-xl font-semibold text-info">
                {num(rawOnly)}
              </p>
            </div>
            <div>
              <p className="mb-0.5 text-xs tracking-wide uppercase opacity-50">Chưa cào</p>
              <p data-numeric className="text-xl font-semibold opacity-60">
                {num(remaining)}
              </p>
            </div>
            <div>
              <p className="mb-0.5 text-xs tracking-wide uppercase opacity-50">Tiến độ tổng</p>
              <p data-numeric className="text-xl font-semibold">
                {summary.total_chapters ? Math.round((summary.translated_count / summary.total_chapters) * 100) : 0}%
              </p>
            </div>
          </div>
        </div>
      </Panel>

      {rows.length === 0 ? (
        <Panel>
          <EmptyState title="Chưa có truyện nào" hint="Thêm truyện ở trang Thư viện để thấy tổng quan tại đây." />
        </Panel>
      ) : (
        <div className="flex flex-col gap-3">
          {rows.map((row) => (
            <EbookRow key={row.slug} row={row} />
          ))}
        </div>
      )}
    </Page>
  );
}
