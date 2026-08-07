import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { InputWithIcon, Select } from "@/components/ui/Field";
import { IconSearch } from "@/components/icons";

/** Tô mức log để quét mắt nhanh — chỉ ba mức đáng phân biệt khi đang theo dõi. */
function lineTone(line: string): string {
  if (/\b(ERROR|CRITICAL|Traceback)\b/.test(line)) return "text-error";
  if (/\bWARNING\b/.test(line)) return "text-warning";
  if (/\bDEBUG\b/.test(line)) return "opacity-40";
  return "opacity-60";
}

export function LogsPage() {
  const [source, setSource] = useState("app");
  const [filter, setFilter] = useState("");
  const [follow, setFollow] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);

  const { data: sources } = useQuery({
    queryKey: ["log-sources"],
    queryFn: () => api.get<{ sources: string[] }>("/api/ui/logs/sources"),
  });

  const { data, isPending } = useQuery({
    queryKey: ["logs", source],
    queryFn: () => api.get<{ lines: string[]; total: number }>(`/api/ui/logs?source=${source}&limit=800`),
    refetchInterval: follow ? 3000 : false,
  });

  const lines = useMemo(() => {
    const all = data?.lines ?? [];
    const q = filter.trim().toLowerCase();
    return q ? all.filter((l) => l.toLowerCase().includes(q)) : all;
  }, [data, filter]);

  useEffect(() => {
    if (!follow) return;
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [lines, follow]);

  return (
    <Page
      title="Nhật ký"
      hint={
        data ? (
          <>
            <span data-numeric>{num(lines.length)}</span> dòng hiển thị trên tổng{" "}
            <span data-numeric>{num(data.total)}</span>
          </>
        ) : (
          "Đang đọc file log"
        )
      }
      actions={
        <>
          <div className="w-36">
            <Select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="w-full"
              aria-label="Nguồn log"
            >
              {(sources?.sources.length ? sources.sources : ["app"]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </div>
          <InputWithIcon
            icon={<IconSearch size={15} />}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Lọc dòng"
            className="w-48"
            aria-label="Lọc dòng log"
          />
          <Button variant={follow ? "primary" : "neutral"} onClick={() => setFollow((v) => !v)}>
            {follow ? "Đang bám cuối" : "Đã dừng"}
          </Button>
        </>
      }
    >
      <Panel className="overflow-hidden">
        <PanelHeader
          title={<span data-numeric>{source}.log</span>}
          hint={follow ? "Tự tải lại mỗi 3 giây" : "Dừng tải lại — cuộn tự do"}
        />
        {isPending ? (
          <EmptyState title="Đang tải nhật ký" />
        ) : lines.length === 0 ? (
          <EmptyState
            title={filter ? "Không có dòng nào khớp" : "File log trống"}
            hint={filter ? "Xóa bộ lọc để xem toàn bộ." : undefined}
          />
        ) : (
          <div
            ref={boxRef}
            className="scroll-slim max-h-[calc(100vh-16rem)] overflow-auto bg-base-200 px-3 py-2"
            onWheel={() => setFollow(false)}
          >
            {lines.map((line, i) => (
              <pre
                key={i}
                className={clsx(
                  "m-0 text-[12px] leading-[1.5] break-words whitespace-pre-wrap",
                  lineTone(line),
                )}
              >
                {line}
              </pre>
            ))}
          </div>
        )}
      </Panel>
    </Page>
  );
}
