import { useEffect, useState } from "react";
import { useParams } from "react-router";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { num } from "@/lib/format";
import {
  useApprovePending,
  useCleanGlossary,
  useClearPending,
  useDeleteGlossaryEntries,
  useDeleteGlossaryEntry,
  useExportGlossary,
  useGlossary,
  useGlossarySuspects,
  useImportGlossary,
  usePendingGlossary,
  useUpsertGlossaryEntry,
  type GlossaryEntry,
  type PendingEntry,
} from "@/lib/glossary";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { SelectionBar } from "@/components/ui/SelectionBar";
import { Checkbox, Input, InputWithIcon, Select, Textarea } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconCaretDown, IconPlus, IconSearch, IconTrash } from "@/components/icons";

const cellInput =
  "input input-xs w-full border-transparent bg-transparent hover:border-base-300 focus:border-primary";

/* ── Hàng đề xuất đang chờ duyệt ─────────────────────────────────────── */

function PendingRow({
  entry,
  checked,
  onToggle,
  slug,
}: {
  entry: PendingEntry;
  checked: boolean;
  onToggle: () => void;
  slug: string;
}) {
  const approve = useApprovePending(slug);
  const clear = useClearPending(slug);
  const toast = useToast();

  return (
    <tr className="border-b border-base-300 bg-warning/10">
      <td className="w-8 px-2 py-1">
        <Checkbox checked={checked} onChange={onToggle} />
      </td>
      <td className="px-2 py-1 text-[13px]">{entry.source}</td>
      <td className="px-2 py-1 text-[13px]">
        {entry.existing_target ? (
          <span className="opacity-50 line-through">{entry.existing_target}</span>
        ) : (
          <span className="opacity-40">(mới)</span>
        )}
        <span className="mx-1 opacity-40">→</span>
        <span className="font-medium">{entry.target}</span>
        {entry.count ? (
          <span data-numeric className="ml-2 text-xs text-warning">
            {entry.count} chỗ / {entry.chapters} chương
          </span>
        ) : null}
      </td>
      <td className="px-2 py-1 text-[13px] opacity-60">{entry.note || "—"}</td>
      <td className="w-40 px-2 py-1 text-right">
        <div className="flex justify-end gap-1">
          <Button
            size="sm"
            variant="primary"
            loading={approve.isPending}
            onClick={() =>
              approve.mutate([{ source: entry.source, target: entry.target, note: entry.note }], {
                onSuccess: () => toast("Đã xếp vào hàng đợi — xem tiến độ ở trang Hàng đợi."),
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              })
            }
          >
            Duyệt
          </Button>
          <Button
            size="sm"
            loading={clear.isPending}
            onClick={() => clear.mutate({ sources: [entry.source] })}
          >
            Bỏ
          </Button>
        </div>
      </td>
    </tr>
  );
}

/* ── Hàng glossary thường ────────────────────────────────────────────── */

function GlossaryRow({
  entry,
  checked,
  onToggle,
  slug,
}: {
  entry: GlossaryEntry;
  checked: boolean;
  onToggle: () => void;
  slug: string;
}) {
  const [source, setSource] = useState(entry.source);
  const [target, setTarget] = useState(entry.target);
  const [note, setNote] = useState(entry.note);
  const upsert = useUpsertGlossaryEntry(slug);
  const del = useDeleteGlossaryEntry(slug);
  const toast = useToast();

  useEffect(() => {
    setSource(entry.source);
    setTarget(entry.target);
    setNote(entry.note);
  }, [entry]);

  const save = (patch: Partial<GlossaryEntry>) => {
    const next = { source, target, note, ...patch };
    if (next.source === entry.source && next.target === entry.target && next.note === entry.note) return;
    if (!next.source.trim() || !next.target.trim()) return;
    upsert.mutate(
      { ...next, originalSource: entry.source },
      { onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") },
    );
  };

  return (
    <tr className={clsx("border-b border-base-300 last:border-b-0", checked && "bg-warning/5")}>
      <td className="w-8 px-2 py-1">
        <Checkbox checked={checked} onChange={onToggle} />
      </td>
      <td className="px-1 py-1">
        <Input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          onBlur={(e) => save({ source: e.target.value.trim() })}
          className={cellInput}
        />
      </td>
      <td className="px-1 py-1">
        <Input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          onBlur={(e) => save({ target: e.target.value.trim() })}
          className={cellInput}
        />
      </td>
      <td className="px-1 py-1">
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={(e) => save({ note: e.target.value.trim() })}
          placeholder="—"
          className={cellInput}
        />
      </td>
      <td className="w-16 px-2 py-1 text-right">
        <button
          type="button"
          onClick={() =>
            del.mutate(entry.source, {
              onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
            })
          }
          className="btn btn-ghost btn-xs text-error"
        >
          Xóa
        </button>
      </td>
    </tr>
  );
}

/* ── Modal thêm mục ──────────────────────────────────────────────────── */

function AddEntryModal({ open, onClose, slug }: { open: boolean; onClose: () => void; slug: string }) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const upsert = useUpsertGlossaryEntry(slug);
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setSource("");
      setTarget("");
      setNote("");
    }
  }, [open]);

  const submit = () => {
    if (!source.trim() || !target.trim()) {
      toast("Cần cả Hán và Việt.", "error");
      return;
    }
    upsert.mutate(
      { source: source.trim(), target: target.trim(), note: note.trim(), originalSource: "" },
      {
        onSuccess: () => {
          toast("Đã thêm.");
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
      title="Thêm mục glossary"
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button variant="primary" loading={upsert.isPending} onClick={submit}>
            Thêm
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <label className="text-[13px]">
          Hán
          <Input autoFocus value={source} onChange={(e) => setSource(e.target.value)} className="mt-1 w-full" />
        </label>
        <label className="text-[13px]">
          Việt
          <Input value={target} onChange={(e) => setTarget(e.target.value)} className="mt-1 w-full" />
        </label>
        <label className="text-[13px]">
          Ghi chú
          <Input value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full" />
        </label>
      </div>
    </Modal>
  );
}

/* ── Modal xuất / nhập cho AI dọn lại ────────────────────────────────── */

function ExportImportModal({ open, onClose, slug }: { open: boolean; onClose: () => void; slug: string }) {
  const [tab, setTab] = useState<"export" | "import">("export");
  const [text, setText] = useState("");
  const exportMut = useExportGlossary(slug);
  const importMut = useImportGlossary(slug);
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setTab("export");
      setText("");
      exportMut.mutate(undefined, { onSuccess: (res) => setText(res.text) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ chạy khi mở modal
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Xuất / Nhập glossary"
      wide
      footer={
        tab === "import" ? (
          <>
            <Button onClick={onClose}>Đóng</Button>
            <Button
              variant="primary"
              loading={importMut.isPending}
              onClick={() =>
                importMut.mutate(text, {
                  onSuccess: (res) => {
                    toast(`Đã nhập: ${res.added} mới, ${res.updated} cập nhật.`);
                    onClose();
                  },
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Nhập vào glossary
            </Button>
          </>
        ) : (
          <Button onClick={onClose}>Đóng</Button>
        )
      }
    >
      <div className="mb-2 flex gap-1.5">
        <Button size="sm" variant={tab === "export" ? "primary" : "neutral"} onClick={() => setTab("export")}>
          Xuất
        </Button>
        <Button
          size="sm"
          variant={tab === "import" ? "primary" : "neutral"}
          onClick={() => {
            setTab("import");
            setText("");
          }}
        >
          Nhập
        </Button>
      </div>
      {tab === "export" ? (
        <>
          <p className="mb-2 text-xs opacity-60">
            Dán vào chat AI kèm yêu cầu dọn lại (dedup, sửa Hán-Việt, gộp mâu thuẫn), rồi dán kết quả vào tab
            Nhập.
          </p>
          <Textarea readOnly value={text} rows={16} className="w-full font-mono text-xs" />
        </>
      ) : (
        <>
          <p className="mb-2 text-xs opacity-60">
            Dán khối <code>GLOSSARY:</code> với các dòng <code>Hán = Việt</code> — merge vào glossary hiện
            có, source trùng thì giá trị mới thắng.
          </p>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={16}
            className="w-full font-mono text-xs"
            placeholder={"GLOSSARY:\n李逸 = Lý Dịch"}
          />
        </>
      )}
    </Modal>
  );
}

/* ── Tab Nghi vấn ────────────────────────────────────────────────────── */

function SuspectsView({ slug }: { slug: string }) {
  const { data, isPending } = useGlossarySuspects(slug, true);

  if (isPending) {
    return (
      <Loading label="Đang quét" />
    );
  }
  if (!data || data.count === 0) {
    return <EmptyState title="Không có mục nào đáng ngờ" hint="Glossary hiện sạch — không trùng target, không lồng nhau." />;
  }

  return (
    <div className="space-y-4 p-3">
      {data.same_target.length > 0 ? (
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold">
            Cùng bản dịch Việt ({data.same_target.length} nhóm)
          </h3>
          <div className="space-y-2">
            {data.same_target.map((group) => (
              <div key={group.target} className="rounded-box border border-base-300 p-2.5">
                <p className="mb-1 text-[13px] font-medium">{group.target}</p>
                <ul className="flex flex-wrap gap-1.5">
                  {group.entries.map((e) => (
                    <li key={e.source}>
                      <Badge>{e.source}</Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {data.nested_source.length > 0 ? (
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold">
            Hán lồng nhau ({data.nested_source.length} cặp)
          </h3>
          <div className="space-y-1.5">
            {data.nested_source.map((pair, i) => (
              <div key={i} className="flex items-center gap-2 rounded-box border border-base-300 px-2.5 py-1.5 text-[13px]">
                <span className="font-medium">{pair.outer.source}</span>
                <span className="opacity-50">→ {pair.outer.target}</span>
                <span className="mx-1 opacity-30">⊃</span>
                <span className="font-medium">{pair.inner.source}</span>
                <span className="opacity-50">→ {pair.inner.target}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {data.conflicts.length > 0 ? (
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold">
            Mâu thuẫn khi dịch ({data.conflicts.length})
          </h3>
          <div className="space-y-1.5">
            {data.conflicts.map((c, i) => (
              <div key={i} className="flex items-center gap-2 rounded-box border border-base-300 px-2.5 py-1.5 text-[13px]">
                <span className="font-medium">{c.source}</span>
                <span className="opacity-50">giữ "{c.kept}"</span>
                <span className="mx-1 opacity-30">vs</span>
                <span className="opacity-50">AI đề xuất "{c.new}"</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function GlossaryPage() {
  const { slug = "" } = useParams();
  const [view, setView] = useState<"all" | "suspects">("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingSelected, setPendingSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [ioOpen, setIoOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const toast = useToast();

  useEffect(() => setPage(1), [search]);
  useEffect(() => setSelected(new Set()), [page, perPage, search]);

  const { data, isPending, isFetching } = useGlossary(slug, { page, per_page: perPage, q: search, sort, dir });
  const { data: pending } = usePendingGlossary(slug);
  const clean = useCleanGlossary(slug);
  const bulkDelete = useDeleteGlossaryEntries(slug);
  const approvePending = useApprovePending(slug);
  const clearPending = useClearPending(slug);

  const toggleSort = (col: string) => {
    if (sort === col) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(col);
      setDir("asc");
    }
  };

  const rows = data?.entries ?? [];
  const allChecked = rows.length > 0 && rows.every((r) => selected.has(r.source));
  const pendingRows = page === 1 ? pending?.entries ?? [] : [];

  return (
    <Page
      title="Glossary"
      hint={`${slug} · tên riêng & thuật ngữ dùng cho prompt dịch — sửa trực tiếp trong bảng, tự lưu khi rời ô`}
      actions={
        <>
          <InputWithIcon
            icon={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm Hán / Việt / ghi chú"
            className="w-60"
          />
          <div role="tablist" className="tabs tabs-box tabs-sm">
            <button
              role="tab"
              type="button"
              className={clsx("tab", view === "all" && "tab-active")}
              onClick={() => setView("all")}
            >
              Tất cả
            </button>
            <button
              role="tab"
              type="button"
              className={clsx("tab", view === "suspects" && "tab-active")}
              onClick={() => setView("suspects")}
            >
              Nghi vấn
            </button>
          </div>
        </>
      }
    >
      {view === "all" ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="ml-auto flex flex-wrap gap-2">
              <Button icon={<IconPlus size={14} />} variant="primary" onClick={() => setAddOpen(true)}>
                Thêm mục
              </Button>
              <Button
                loading={clean.isPending}
                title="Trim khoảng trắng, bỏ dòng thiếu Hán/Việt, gộp trùng"
                onClick={() =>
                  clean.mutate(undefined, {
                    onSuccess: (res) => toast(`Đã dọn: bỏ ${res.removed} mục thừa/trùng.`),
                  })
                }
              >
                Dọn dữ liệu
              </Button>
              <Button onClick={() => setIoOpen(true)}>Xuất / Nhập</Button>
            </div>
          </div>

          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-base-300 px-3 py-2 text-[13px]">
              <span data-numeric className="opacity-60">
                {data ? `${num(data.total)} mục` : "—"}
                {pending && pending.count > 0 ? ` · ${num(pending.count)} chờ duyệt` : ""}
              </span>
              {data && data.pages > 1 ? (
                <div className="flex items-center gap-2">
                  <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                    ← Trước
                  </Button>
                  <span data-numeric className="opacity-60">
                    {page}/{data.pages}
                  </span>
                  <Button size="sm" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
                    Sau →
                  </Button>
                  <Select value={String(perPage)} onChange={(e) => setPerPage(Number(e.target.value))} className="ml-1">
                    {[25, 50, 100, 200].map((n) => (
                      <option key={n} value={n}>
                        {n}/trang
                      </option>
                    ))}
                  </Select>
                </div>
              ) : null}
            </div>

            {isPending ? (
              <SkeletonTable rows={6} cols={4} />
            ) : rows.length === 0 && pendingRows.length === 0 ? (
              <EmptyState
                title={search ? "Không có mục nào khớp" : "Glossary đang trống"}
                hint={search ? "Thử từ khóa khác." : 'Bấm "Thêm mục", hoặc glossary sẽ tự sinh trong lúc dịch.'}
              />
            ) : (
              <div className={clsx("overflow-x-auto", isFetching && "opacity-60")}>
                <table className="w-full min-w-[52rem] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-base-300 bg-base-200/60">
                      <th className="w-8 px-2 py-1.5">
                        <Checkbox
                          checked={allChecked}
                          onChange={() =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              rows.forEach((r) => (allChecked ? next.delete(r.source) : next.add(r.source)));
                              return next;
                            })
                          }
                        />
                      </th>
                      {[
                        { key: "source", label: "Hán" },
                        { key: "target", label: "Việt" },
                      ].map((c) => (
                        <th
                          key={c.key}
                          onClick={() => toggleSort(c.key)}
                          className="cursor-pointer px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40 select-none"
                        >
                          <span className="inline-flex items-center gap-1">
                            {c.label}
                            {sort === c.key ? (
                              <IconCaretDown size={10} className={dir === "desc" ? "rotate-180" : ""} />
                            ) : null}
                          </span>
                        </th>
                      ))}
                      <th className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                        Ghi chú
                      </th>
                      <th className="w-16 px-2 py-1.5" />
                    </tr>
                  </thead>
                  <tbody>
                    {pendingRows.map((p) => (
                      <PendingRow
                        key={`pending-${p.source}`}
                        entry={p}
                        slug={slug}
                        checked={pendingSelected.has(p.source)}
                        onToggle={() =>
                          setPendingSelected((prev) => {
                            const next = new Set(prev);
                            if (next.has(p.source)) next.delete(p.source);
                            else next.add(p.source);
                            return next;
                          })
                        }
                      />
                    ))}
                    {rows.map((entry) => (
                      <GlossaryRow
                        key={entry.source}
                        entry={entry}
                        slug={slug}
                        checked={selected.has(entry.source)}
                        onToggle={() =>
                          setSelected((prev) => {
                            const next = new Set(prev);
                            if (next.has(entry.source)) next.delete(entry.source);
                            else next.add(entry.source);
                            return next;
                          })
                        }
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {selected.size > 0 || pendingSelected.size > 0 ? (
            <SelectionBar
              count={selected.size + pendingSelected.size}
              noun="mục đã chọn"
              onClear={() => {
                setSelected(new Set());
                setPendingSelected(new Set());
              }}
            >
              {pendingSelected.size > 0 ? (
                <>
                  <Button
                    variant="primary"
                    loading={approvePending.isPending}
                    onClick={() =>
                      approvePending.mutate(
                        pendingRows
                          .filter((p) => pendingSelected.has(p.source))
                          .map((p) => ({ source: p.source, target: p.target, note: p.note })),
                        {
                          onSuccess: () => {
                            setPendingSelected(new Set());
                            toast("Đã xếp vào hàng đợi — xem tiến độ ở trang Hàng đợi.");
                          },
                        },
                      )
                    }
                  >
                    Duyệt đề xuất ({pendingSelected.size})
                  </Button>
                  <Button
                    loading={clearPending.isPending}
                    onClick={() =>
                      clearPending.mutate(
                        { sources: [...pendingSelected] },
                        { onSuccess: () => setPendingSelected(new Set()) },
                      )
                    }
                  >
                    Bỏ đề xuất
                  </Button>
                </>
              ) : null}
              {selected.size > 0 ? (
                <Button variant="danger" icon={<IconTrash size={14} />} onClick={() => setConfirmBulkDelete(true)}>
                  Xóa đã chọn ({selected.size})
                </Button>
              ) : null}
            </SelectionBar>
          ) : null}
        </>
      ) : (
        <Panel className="overflow-hidden">
          <SuspectsView slug={slug} />
        </Panel>
      )}

      <AddEntryModal open={addOpen} onClose={() => setAddOpen(false)} slug={slug} />
      <ExportImportModal open={ioOpen} onClose={() => setIoOpen(false)} slug={slug} />
      <ConfirmDialog
        open={confirmBulkDelete}
        onCancel={() => setConfirmBulkDelete(false)}
        onConfirm={() =>
          bulkDelete.mutate([...selected], {
            onSuccess: () => {
              setConfirmBulkDelete(false);
              setSelected(new Set());
            },
          })
        }
        title="Xóa mục đã chọn"
        body={`Xóa ${selected.size} mục glossary đã chọn? Không thể hoàn tác.`}
        confirmLabel="Xóa"
        destructive
        pending={bulkDelete.isPending}
      />
    </Page>
  );
}
