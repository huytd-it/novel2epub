import { useState } from "react";
import { Link } from "react-router";

import { Page } from "@/app/Shell";
import { apiUrl } from "@/lib/api";
import { bytes, num } from "@/lib/format";
import {
  usePurgeMt,
  usePurgeRaw,
  useRemoveEpub,
  useStorageOverview,
  type StorageRow,
} from "@/lib/storage";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconDownload } from "@/components/icons";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-field bg-base-200 p-2.5">
      <p className="text-[10px] tracking-[0.1em] uppercase opacity-50">{label}</p>
      <p data-numeric className="text-lg leading-tight font-semibold">
        {value}
      </p>
      {hint ? (
        <p data-numeric className="text-[11px] opacity-50">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type ConfirmKind = "raw" | "mt" | "epub";
type Confirm = { row: StorageRow; kind: ConfirmKind } | null;

function StorageRowCard({ row, onAsk }: { row: StorageRow; onAsk: (c: Confirm) => void }) {
  const r = row.report;
  return (
    <Panel className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <Link to={`/ebooks/${row.slug}`} className="font-display text-[15px] font-semibold hover:text-primary">
          {row.title}
        </Link>
        <span data-numeric className="badge badge-neutral">
          {bytes(r.total)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Metric label="Raw" value={bytes(r.raw)} hint={`${num(r.raw_chapters)} chương`} />
        <Metric label="Translated" value={bytes(r.translated)} hint={`${num(r.translated_chapters)} chương`} />
        <Metric label="Glossary" value={bytes(r.glossary)} hint={`${num(r.glossary_entries)} mục`} />
        <Metric label="EPUB" value={r.epub_exists ? bytes(r.epub) : "—"} hint={r.epub_exists ? "có" : "chưa có"} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onAsk({ row, kind: "raw" })}>
          Xóa raw
        </Button>
        <Button size="sm" onClick={() => onAsk({ row, kind: "mt" })}>
          Xóa MT
        </Button>
        <Button size="sm" onClick={() => onAsk({ row, kind: "epub" })}>
          Xóa EPUB
        </Button>
        <a
          href={apiUrl(`/storage/${row.slug}/archive`)}
          className="btn btn-sm btn-primary inline-flex items-center gap-1.5"
        >
          <IconDownload size={13} /> Archive (.zip)
        </a>
      </div>
    </Panel>
  );
}

const CONFIRM_COPY: Record<ConfirmKind, { title: string; body: (name: string) => string }> = {
  raw: {
    title: "Xóa raw",
    body: (name) => `Xóa toàn bộ file raw của ${name}? Bản dịch không bị ảnh hưởng.`,
  },
  mt: {
    title: "Xóa MT",
    body: (name) =>
      `Xóa snapshot bản dịch máy (MT) của ${name}? Chỉ xóa translated_mt/, không đụng bản đang biên tập.`,
  },
  epub: {
    title: "Xóa EPUB",
    body: (name) => `Xóa file EPUB của ${name}? Cần build lại để có lại.`,
  },
};

export function StoragePage() {
  const { data, isPending } = useStorageOverview();
  const [confirm, setConfirm] = useState<Confirm>(null);
  const purgeRaw = usePurgeRaw();
  const purgeMt = usePurgeMt();
  const removeEpub = useRemoveEpub();
  const toast = useToast();

  const pending = purgeRaw.isPending || purgeMt.isPending || removeEpub.isPending;

  const run = () => {
    if (!confirm) return;
    const { row, kind } = confirm;
    const mutation = kind === "raw" ? purgeRaw : kind === "mt" ? purgeMt : removeEpub;
    mutation.mutate(row.slug, {
      onSuccess: () => {
        setConfirm(null);
        toast(`Đã ${CONFIRM_COPY[kind].title.toLowerCase()} cho ${row.title}.`);
      },
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };

  return (
    <Page title="Lưu trữ & Dung lượng" hint="Tổng dung lượng raw, translated, glossary, EPUB theo từng truyện — dọn dẹp khi cần">
      {isPending ? (
        <Loading label="Đang tính dung lượng" />
      ) : !data || data.rows.length === 0 ? (
        <Panel>
          <EmptyState title="Chưa có dữ liệu" hint="Thêm truyện và chạy crawl/dịch để thấy báo cáo lưu trữ." />
        </Panel>
      ) : (
        <>
          <div className="flex flex-col gap-3">
            {data.rows.map((row) => (
              <StorageRowCard key={row.slug} row={row} onAsk={setConfirm} />
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between rounded-box border border-warning/40 bg-warning/10 px-4 py-3">
            <span className="text-[13px] font-medium">Tổng dung lượng</span>
            <span data-numeric className="text-xl font-semibold text-warning">
              {bytes(data.grand_total)}
            </span>
          </div>
        </>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onCancel={() => setConfirm(null)}
        onConfirm={run}
        title={confirm ? CONFIRM_COPY[confirm.kind].title : ""}
        body={confirm ? CONFIRM_COPY[confirm.kind].body(confirm.row.title) : ""}
        confirmLabel={confirm ? CONFIRM_COPY[confirm.kind].title : undefined}
        destructive
        pending={pending}
      />
    </Page>
  );
}
