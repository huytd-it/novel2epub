import { useEffect, useState } from "react";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { num } from "@/lib/format";
import {
  useDeleteIdiom,
  useDeleteIdioms,
  useExportIdioms,
  useIdioms,
  useImportIdioms,
  useSeedIdioms,
  useUpsertIdiom,
  type IdiomEntry,
} from "@/lib/idioms";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Checkbox, Input, InputWithIcon, Select, Textarea } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconCaretDown, IconPlus, IconSearch, IconTrash } from "@/components/icons";

const cellInput = "input input-xs w-full border-transparent bg-transparent hover:border-base-300 focus:border-primary";

/* ── Một hàng — autosave khi rời ô, đọc thẳng từ event tránh closure cũ ── */

function IdiomRow({
  entry,
  checked,
  onToggle,
}: {
  entry: IdiomEntry;
  checked: boolean;
  onToggle: () => void;
}) {
  const [source, setSource] = useState(entry.source);
  const [target, setTarget] = useState(entry.target);
  const [literals, setLiterals] = useState(entry.literals);
  const upsert = useUpsertIdiom();
  const del = useDeleteIdiom();
  const toast = useToast();

  useEffect(() => {
    setSource(entry.source);
    setTarget(entry.target);
    setLiterals(entry.literals);
  }, [entry]);

  const save = (patch: Partial<IdiomEntry>) => {
    const next = { source, target, literals, protect: entry.protect, ...patch };
    if (
      next.source === entry.source &&
      next.target === entry.target &&
      next.literals === entry.literals &&
      next.protect === entry.protect
    ) {
      return;
    }
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
          value={literals}
          onChange={(e) => setLiterals(e.target.value)}
          onBlur={(e) => save({ literals: e.target.value.trim() })}
          placeholder={entry.protect ? "— protect bật —" : "bản máy 1 | bản máy 2"}
          disabled={entry.protect}
          className={clsx(cellInput, entry.protect && "opacity-50")}
        />
      </td>
      <td className="w-16 px-2 py-1 text-center">
        <Checkbox
          checked={entry.protect}
          onChange={(e) => save({ protect: e.target.checked })}
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

/* ── Modal thêm mục mới ──────────────────────────────────────────────── */

function AddIdiomModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [literals, setLiterals] = useState("");
  const [protect, setProtect] = useState(false);
  const upsert = useUpsertIdiom();
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setSource("");
      setTarget("");
      setLiterals("");
      setProtect(false);
    }
  }, [open]);

  const submit = () => {
    if (!source.trim() || !target.trim()) {
      toast("Cần cả Hán và bản dịch đẹp.", "error");
      return;
    }
    upsert.mutate(
      { source: source.trim(), target: target.trim(), literals: literals.trim(), protect, originalSource: "" },
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
      title="Thêm mục thành ngữ"
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
          Bản đẹp
          <Input value={target} onChange={(e) => setTarget(e.target.value)} className="mt-1 w-full" />
        </label>
        <label className="text-[13px]">
          Bản máy (ngăn bằng <code>|</code>)
          <Input
            value={literals}
            onChange={(e) => setLiterals(e.target.value)}
            disabled={protect}
            className="mt-1 w-full"
          />
        </label>
        <label className="flex items-center gap-2 text-[13px]">
          <Checkbox checked={protect} onChange={(e) => setProtect(e.target.checked)} />
          protect (thay Hán bằng placeholder trước khi đưa vào MT)
        </label>
      </div>
    </Modal>
  );
}

/* ── Modal xuất / nhập text ──────────────────────────────────────────── */

function ExportImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<"export" | "import">("export");
  const [text, setText] = useState("");
  const exportMut = useExportIdioms();
  const importMut = useImportIdioms();
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setTab("export");
      exportMut.mutate(undefined, { onSuccess: (res) => setText(res.text) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ chạy khi mở modal
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Xuất / Nhập thành ngữ"
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
              Nhập vào kho
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
        <Button size="sm" variant={tab === "import" ? "primary" : "neutral"} onClick={() => setTab("import")}>
          Nhập
        </Button>
      </div>
      {tab === "export" ? (
        <>
          <p className="mb-2 text-xs opacity-60">
            Định dạng <code>Hán = bản đẹp | bản máy… / @protect</code>, 1 dòng / mục.
          </p>
          <Textarea readOnly value={text} rows={14} className="w-full font-mono text-xs" />
        </>
      ) : (
        <>
          <p className="mb-2 text-xs opacity-60">
            Dán danh sách cùng định dạng vào đây — trùng Hán sẽ được cập nhật.
          </p>
          <Textarea
            value={tab === "import" && text === exportMut.data?.text ? "" : text}
            onChange={(e) => setText(e.target.value)}
            rows={14}
            className="w-full font-mono text-xs"
            placeholder="妙笔生花 = văn hay chữ tốt | diệu bút sinh hoa"
          />
        </>
      )}
    </Modal>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function IdiomsPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [ioOpen, setIoOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const toast = useToast();

  useEffect(() => setPage(1), [search]);
  useEffect(() => setSelected(new Set()), [page, perPage, search]);

  const { data, isPending, isFetching } = useIdioms({ page, per_page: perPage, q: search, sort, dir });
  const seed = useSeedIdioms();
  const bulkDelete = useDeleteIdioms();

  const toggleSort = (col: string) => {
    if (sort === col) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(col);
      setDir("asc");
    }
  };

  const rows = data?.entries ?? [];
  const allChecked = rows.length > 0 && rows.every((r) => selected.has(r.source));

  return (
    <Page
      title="Từ điển chung"
      hint="Thành ngữ / khẩu ngữ dùng chung mọi truyện — LLM nhận làm gợi ý prompt, MT cục bộ tự thay bản máy → bản đẹp"
      actions={
        <>
          <InputWithIcon
            icon={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm Hán / bản đẹp / bản máy"
            className="w-64"
          />
          {selected.size > 0 ? (
            <Button
              variant="danger"
              icon={<IconTrash size={14} />}
              onClick={() => setConfirmBulkDelete(true)}
            >
              Xóa đã chọn ({selected.size})
            </Button>
          ) : null}
          <Button icon={<IconPlus size={14} />} variant="primary" onClick={() => setAddOpen(true)}>
            Thêm mục
          </Button>
          <Button
            loading={seed.isPending}
            onClick={() =>
              seed.mutate(undefined, {
                onSuccess: (res) =>
                  toast(res.seeded > 0 ? `Đã nạp ${res.seeded} mục mẫu.` : "Kho đã có dữ liệu, không nạp đè."),
              })
            }
            title="Nạp bộ idiom mẫu (chỉ khi kho đang trống)"
          >
            Nạp bộ mẫu
          </Button>
          <Button onClick={() => setIoOpen(true)}>Xuất / Nhập</Button>
        </>
      }
    >
      <Panel className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-base-300 px-3 py-2 text-[13px]">
          <span data-numeric className="opacity-60">
            {data ? `${num(data.total)} mục` : "—"}
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
          <div className="flex items-center justify-center gap-2 py-16 text-sm opacity-60">
            <Spinner /> Đang tải
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={search ? "Không có mục nào khớp" : "Kho đang trống"}
            hint={search ? "Thử từ khóa khác." : 'Bấm "Nạp bộ mẫu" hoặc "Thêm mục" để bắt đầu.'}
          />
        ) : (
          <div className={clsx("overflow-x-auto", isFetching && "opacity-60")}>
            <table className="w-full min-w-[48rem] border-collapse text-left">
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
                    { key: "target", label: "Bản đẹp" },
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
                    Bản máy
                  </th>
                  <th className="w-16 px-2 py-1.5 text-center text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                    protect
                  </th>
                  <th className="w-16 px-2 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <IdiomRow
                    key={entry.source}
                    entry={entry}
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

      <AddIdiomModal open={addOpen} onClose={() => setAddOpen(false)} />
      <ExportImportModal open={ioOpen} onClose={() => setIoOpen(false)} />
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
        body={`Xóa ${selected.size} mục thành ngữ đã chọn? Không thể hoàn tác.`}
        confirmLabel="Xóa"
        destructive
        pending={bulkDelete.isPending}
      />
    </Page>
  );
}
