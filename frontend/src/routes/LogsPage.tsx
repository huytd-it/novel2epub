import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { InputWithIcon, Select } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { IconCheck, IconCopy, IconDownload, IconSearch, IconTrash } from "@/components/icons";

type LogEntry = {
  id: number;
  ts: number;
  level: string;
  logger: string;
  message: string;
  job_id: string;
};

type LogsResp = { entries: LogEntry[]; total: number };
type LogsStats = {
  total: number;
  by_level: Record<string, number>;
  oldest_ts: number | null;
  newest_ts: number | null;
};
type LogSource = { logger: string; count: number };

const PAGE_SIZE = 300;
/** Mức mặc định bật khi mở trang — DEBUG thường chỉ là noise khi dò lỗi. */
const DEFAULT_LEVELS = ["INFO", "WARNING", "ERROR", "CRITICAL"];
const LEVEL_ORDER = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];

const levelTone: Record<string, string> = {
  ERROR: "text-error",
  CRITICAL: "text-error font-semibold",
  WARNING: "text-warning",
  DEBUG: "opacity-40",
};

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString("vi-VN")} ${d.toLocaleTimeString("vi-VN", { hour12: false })}`;
}

/** navigator.clipboard chỉ có ở secure context — qua HTTP trên LAN phải dùng
    fallback textarea. Trả true nếu sao chép thành công. */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // rơi xuống fallback bên dưới
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

function logLine(entry: LogEntry): string {
  return `${fmtTime(entry.ts)} [${entry.level}] ${entry.logger}: ${entry.message}`;
}

export function LogsPage() {
  const queryClient = useQueryClient();
  const boxRef = useRef<HTMLDivElement>(null);

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [levels, setLevels] = useState<string[]>(DEFAULT_LEVELS);
  const [source, setSource] = useState("");
  const [follow, setFollow] = useState(true);
  const [olderPages, setOlderPages] = useState<LogEntry[][]>([]);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearScope, setClearScope] = useState<"all" | "filter" | "7d" | "30d">("all");
  /** Dòng đang mở chi tiết (mặc định rút gọn 1 dòng). */
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  /** Dòng vừa copy — đổi icon thành dấu check trong 1.2s. */
  const [copiedId, setCopiedId] = useState<number | null>(null);

  function toggleExpanded(id: number) {
    setExpandedIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function copyEntry(entry: LogEntry) {
    if (await copyText(logLine(entry))) {
      setCopiedId(entry.id);
      setTimeout(() => setCopiedId((cur) => (cur === entry.id ? null : cur)), 1200);
    }
  }

  // Gõ tìm kiếm debounce 300ms — mỗi ký tự là một truy vấn SQL LIKE phía server.
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const params = useMemo(() => {
    const sp = new URLSearchParams();
    if (q) sp.set("q", q);
    if (levels.length && levels.length < LEVEL_ORDER.length) sp.set("levels", levels.join(","));
    if (source) sp.set("source", source);
    sp.set("limit", String(PAGE_SIZE));
    return sp.toString();
  }, [q, levels, source]);

  const filterActive = Boolean(q || source || levels.length < LEVEL_ORDER.length);

  // Đổi bộ lọc → bỏ các trang cũ đã tải, quay lại trang đầu.
  useEffect(() => {
    setOlderPages([]);
  }, [params]);

  const { data: stats } = useQuery({
    queryKey: ["log-stats"],
    queryFn: () => api.get<LogsStats>("/api/ui/logs/stats"),
    refetchInterval: follow ? 3000 : false,
  });

  const { data: sources } = useQuery({
    queryKey: ["log-sources"],
    queryFn: () => api.get<{ sources: LogSource[] }>("/api/ui/logs/sources"),
  });

  const { data, isPending, dataUpdatedAt } = useQuery({
    queryKey: ["logs", params],
    queryFn: () => api.get<LogsResp>(`/api/ui/logs?${params}`),
    refetchInterval: follow ? 3000 : false,
  });

  const entries = useMemo(
    () => [...(data?.entries ?? []), ...olderPages.flat()],
    [data, olderPages],
  );
  const hasMore = (data?.total ?? 0) > entries.length;

  async function loadOlder() {
    const lastId = entries.at(-1)?.id;
    if (!lastId) return;
    setLoadingOlder(true);
    try {
      setFollow(false);
      const resp = await api.get<LogsResp>(`/api/ui/logs?${params}&before_id=${lastId}`);
      if (resp.entries.length) setOlderPages((p) => [...p, resp.entries]);
    } finally {
      setLoadingOlder(false);
    }
  }

  function toggleLevel(level: string) {
    setLevels((cur) => {
      if (cur.includes(level)) {
        // Không cho bỏ trống toàn bộ mức — lọc rỗng sẽ trả cả DEBUG.
        if (cur.length === 1) return cur;
        return cur.filter((l) => l !== level);
      }
      return [...cur, level];
    });
  }

  async function exportLogs() {
    const text = await api.get<string>(`/api/ui/logs/export?${params}`);
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "novel2epub-logs.txt";
    a.click();
    URL.revokeObjectURL(url);
  }

  const deleteEntry = useMutation({
    mutationFn: (id: number) => api.del(`/api/ui/logs/${id}`),
    onSuccess: (_data, id) => {
      // Dòng nằm ngoài trang 1 (olderPages) không được invalidate phủ tới —
      // tự gỡ khỏi state local để biến mất ngay.
      setOlderPages((pages) =>
        pages.map((page) => page.filter((e) => e.id !== id)).filter((p) => p.length > 0),
      );
      void queryClient.invalidateQueries({ queryKey: ["logs"] });
      void queryClient.invalidateQueries({ queryKey: ["log-stats"] });
      void queryClient.invalidateQueries({ queryKey: ["log-sources"] });
    },
  });

  const clearMut = useMutation({
    mutationFn: () => {
      const sp = new URLSearchParams();
      if (clearScope === "filter") {
        if (q) sp.set("q", q);
        if (levels.length && levels.length < LEVEL_ORDER.length)
          sp.set("levels", levels.join(","));
        if (source) sp.set("source", source);
      }
      if (clearScope === "7d") sp.set("older_than_days", "7");
      if (clearScope === "30d") sp.set("older_than_days", "30");
      return api.del<{ deleted: number }>(`/api/ui/logs?${sp.toString()}`);
    },
    onSuccess: () => {
      setClearOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["logs"] });
      void queryClient.invalidateQueries({ queryKey: ["log-stats"] });
      void queryClient.invalidateQueries({ queryKey: ["log-sources"] });
    },
  });

  return (
    <Page
      title="Nhật ký"
      hint={
        stats ? (
          <>
            <span data-numeric>{num(entries.length)}</span> /{" "}
            <span data-numeric>{num(stats.total)}</span> dòng
            {stats.newest_ts ? <> · mới nhất {fmtTime(stats.newest_ts)}</> : null}
          </>
        ) : (
          "Đang đọc nhật ký từ SQLite"
        )
      }
      actions={
        <>
          <div className="w-44">
            <Select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="w-full"
              aria-label="Nguồn log"
            >
              <option value="">Mọi nguồn</option>
              {(sources?.sources ?? []).map((s) => (
                <option key={s.logger} value={s.logger}>
                  {s.logger} ({num(s.count)})
                </option>
              ))}
            </Select>
          </div>
          <InputWithIcon
            icon={<IconSearch size={15} />}
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Tìm trong nội dung…"
            className="w-52"
            aria-label="Tìm trong nội dung log"
          />
          <Button icon={<IconDownload size={15} />} onClick={() => void exportLogs()}>
            Xuất
          </Button>
          <Button variant="danger" icon={<IconTrash size={15} />} onClick={() => setClearOpen(true)}>
            Dọn
          </Button>
          <Button variant={follow ? "primary" : "neutral"} onClick={() => setFollow((v) => !v)}>
            {follow ? "Đang theo dõi" : "Tạm dừng"}
          </Button>
        </>
      }
    >
      <Panel className="overflow-hidden">
        <PanelHeader
          title={
            <div className="flex flex-wrap items-center gap-1.5">
              {LEVEL_ORDER.map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => toggleLevel(level)}
                  className={clsx(
                    "badge badge-sm cursor-pointer border border-base-300 select-none",
                    levels.includes(level) ? levelTone[level] ?? "badge-ghost" : "badge-ghost opacity-35",
                  )}
                  title={levels.includes(level) ? `Ẩn ${level}` : `Hiện ${level}`}
                >
                  {level}{" "}
                  <span data-numeric className="opacity-60">
                    {num(stats?.by_level?.[level] ?? 0)}
                  </span>
                </button>
              ))}
            </div>
          }
          hint={
            follow
              ? "Tự tải lại mỗi 3 giây — bấm Tạm dừng để cuộn tự do"
              : `Cập nhật lúc ${new Date(dataUpdatedAt).toLocaleTimeString("vi-VN", { hour12: false })}`
          }
          actions={
            hasMore ? (
              <Button size="sm" loading={loadingOlder} onClick={() => void loadOlder()}>
                Tải dòng cũ hơn
              </Button>
            ) : undefined
          }
        />
        {isPending ? (
          <EmptyState title="Đang tải nhật ký" />
        ) : entries.length === 0 ? (
          <EmptyState
            title={filterActive ? "Không có dòng nào khớp" : "Nhật ký trống"}
            hint={
              filterActive
                ? "Nới lỏng bộ lọc hoặc mức log đang tắt."
                : "Log sẽ xuất hiện khi crawler/dịch/build chạy."
            }
          />
        ) : (
          <div ref={boxRef} className="scroll-slim max-h-[calc(100vh-17rem)] overflow-auto bg-base-200 px-3 py-2">
            {entries.map((entry) => {
              const expanded = expandedIds.has(entry.id);
              return (
                <div
                  key={entry.id}
                  className={clsx(
                    "group flex items-start gap-2 rounded px-1 -mx-1",
                    expanded ? "bg-base-300/40" : "hover:bg-base-300/30",
                  )}
                >
                  <span className="shrink-0 pt-px text-[11px] tabular-nums opacity-45" data-numeric>
                    {fmtTime(entry.ts)}
                  </span>
                  <span
                    className={clsx(
                      "w-[4.5rem] shrink-0 text-[11px] font-medium uppercase",
                      levelTone[entry.level] ?? "opacity-50",
                    )}
                  >
                    {entry.level}
                  </span>
                  <pre
                    role={expanded ? undefined : "button"}
                    tabIndex={expanded ? undefined : 0}
                    aria-expanded={expanded}
                    onClick={() => toggleExpanded(entry.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleExpanded(entry.id);
                      }
                    }}
                    title={expanded ? "Bấm để thu gọn" : "Bấm để xem chi tiết"}
                    className={clsx(
                      "m-0 min-w-0 flex-1 cursor-pointer text-[12px] leading-[1.5]",
                      expanded
                        ? "whitespace-pre-wrap break-words"
                        : "truncate whitespace-nowrap",
                      levelTone[entry.level] ?? "opacity-70",
                    )}
                  >
                    {entry.logger ? `${entry.logger}: ` : ""}
                    {entry.message}
                  </pre>
                  <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity duration-100 focus-within:opacity-100 group-hover:opacity-100">
                    <button
                      type="button"
                      aria-label={`Copy dòng log ${entry.id}`}
                      title="Copy"
                      onClick={() => void copyEntry(entry)}
                      className="btn btn-ghost btn-xs px-1"
                    >
                      {copiedId === entry.id ? (
                        <IconCheck size={13} className="text-success" />
                      ) : (
                        <IconCopy size={13} />
                      )}
                    </button>
                    <button
                      type="button"
                      aria-label={`Xoá dòng log ${entry.id}`}
                      title="Xoá dòng này"
                      disabled={deleteEntry.isPending && deleteEntry.variables === entry.id}
                      onClick={() => deleteEntry.mutate(entry.id)}
                      className="btn btn-ghost btn-xs px-1 text-error/70 hover:text-error"
                    >
                      <IconTrash size={13} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      <ConfirmDialog
        open={clearOpen}
        onCancel={() => setClearOpen(false)}
        onConfirm={() => clearMut.mutate()}
        title="Dọn nhật ký"
        confirmLabel="Xoá nhật ký"
        destructive
        pending={clearMut.isPending}
        body={
          <div className="flex flex-col gap-2">
            <Select
              value={clearScope}
              onChange={(e) => setClearScope(e.target.value as typeof clearScope)}
              aria-label="Phạm vi xoá"
            >
              <option value="all">Toàn bộ nhật ký</option>
              <option value="7d">Cũ hơn 7 ngày</option>
              <option value="30d">Cũ hơn 30 ngày</option>
              <option value="filter" disabled={!filterActive}>
                Chỉ những dòng khớp bộ lọc đang mở
              </option>
            </Select>
            <p className="opacity-60">
              Nhật ký lưu trong SQLite bị xoá không phục hồi được. Job history không bị ảnh hưởng.
            </p>
          </div>
        }
      />
    </Page>
  );
}
