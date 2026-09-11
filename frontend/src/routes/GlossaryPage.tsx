import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { num } from "@/lib/format";
import {
  useApplyGlossaryEdits,
  useApprovePending,
  useCleanGlossary,
  useClearPending,
  useDeleteGlossaryEntries,
  useDeleteGlossaryEntry,
  useExportGlossary,
  useGlossary,
  useGlossaryAiRetranslate,
  useGlossaryFlags,
  useGlossarySuspects,
  useImportGlossary,
  usePendingGlossary,
  usePreviewGlossaryEdits,
  useUpsertGlossaryEntry,
  type GlossaryEdit,
  type GlossaryEditKind,
  type GlossaryEntry,
  type PendingEntry,
} from "@/lib/glossary";
import { useEbookSettings } from "@/lib/settings";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { SelectionBar } from "@/components/ui/SelectionBar";
import { Checkbox, Input, InputWithIcon, Select, Textarea } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge, type Tone } from "@/components/ui/Badge";
import { DiffText } from "@/components/DiffText";
import { useToast } from "@/components/ui/Toast";
import {
  IconCaretDown,
  IconFilter,
  IconPlus,
  IconRevert,
  IconSearch,
  IconSparkle,
  IconTrash,
  IconWarning,
} from "@/components/icons";

const cellInput =
  "input input-xs w-full border-transparent bg-transparent hover:border-base-300 focus:border-primary";

/**
 * Bản nháp các dòng đã sửa, khoá theo source GỐC — đổi Hán vẫn giữ nguyên khoá
 * nên server biết phải xoá mục cũ nào. Nháp sống qua đổi trang/tìm kiếm: bấm
 * "Áp dụng" để xem trước rồi ghi cả đợt một lần.
 */
type Drafts = Record<string, GlossaryEdit>;

const sameValues = (draft: GlossaryEdit, entry: GlossaryEntry) =>
  draft.source === entry.source && draft.target === entry.target && draft.note === entry.note;

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

/**
 * Sửa TẠI CHỖ nhưng KHÔNG tự lưu: mọi thay đổi chỉ vào `drafts` của trang, ghi
 * xuống DB khi bấm "Áp dụng". `memo` + callback ổn định (nhận entry/source làm
 * tham số) để gõ ở một dòng không render lại cả bảng 200 dòng.
 */
const GlossaryRow = memo(function GlossaryRow({
  entry,
  draft,
  checked,
  slug,
  onToggle,
  onEdit,
  onRevert,
  onDeleted,
}: {
  entry: GlossaryEntry;
  draft?: GlossaryEdit;
  checked: boolean;
  slug: string;
  onToggle: (source: string) => void;
  onEdit: (entry: GlossaryEntry, patch: Partial<GlossaryEntry>) => void;
  onRevert: (source: string) => void;
  onDeleted: (source: string) => void;
}) {
  const del = useDeleteGlossaryEntry(slug);
  const toast = useToast();
  const value = draft ?? entry;

  const field = (key: "source" | "target" | "note") => ({
    value: value[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => onEdit(entry, { [key]: e.target.value }),
    onBlur: (e: React.FocusEvent<HTMLInputElement>) => onEdit(entry, { [key]: e.target.value.trim() }),
    className: clsx(cellInput, value[key] !== entry[key] && "border-warning bg-warning/10"),
  });

  return (
    <tr
      className={clsx(
        "border-b border-base-300 last:border-b-0",
        (draft || checked) && "bg-warning/5",
      )}
    >
      <td className="w-8 px-2 py-1">
        <Checkbox checked={checked} onChange={() => onToggle(entry.source)} />
      </td>
      <td className="px-1 py-1">
        <Input {...field("source")} />
      </td>
      <td className="px-1 py-1">
        <Input {...field("target")} />
      </td>
      <td className="px-1 py-1">
        <Input {...field("note")} placeholder="—" />
      </td>
      <td className="w-24 px-2 py-1 text-right">
        <div className="flex justify-end gap-0.5">
          {draft ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<IconRevert size={14} />}
              title="Hoàn tác dòng này"
              aria-label="Hoàn tác dòng này"
              onClick={() => onRevert(entry.source)}
            />
          ) : null}
          <button
            type="button"
            onClick={() =>
              del.mutate(entry.source, {
                onSuccess: () => onDeleted(entry.source),
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              })
            }
            className="btn btn-ghost btn-xs text-error"
          >
            Xóa
          </button>
        </div>
      </td>
    </tr>
  );
});

/* ── Modal xem trước & áp dụng cả đợt sửa ────────────────────────────── */

const KIND_LABEL: Record<GlossaryEditKind, { text: string; tone: Tone }> = {
  new: { text: "Thêm mới", tone: "celadon" },
  update: { text: "Sửa", tone: "gold" },
  rename: { text: "Đổi Hán", tone: "indigo" },
  unchanged: { text: "Không đổi", tone: "neutral" },
};

function ApplyEditsModal({
  open,
  onClose,
  slug,
  edits,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  edits: GlossaryEdit[];
  onApplied: () => void;
}) {
  const preview = usePreviewGlossaryEdits(slug);
  const apply = useApplyGlossaryEdits(slug);
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    preview.reset();
    preview.mutate(edits);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ đối chiếu lại khi mở modal
  }, [open]);

  const data = preview.data;
  const blocked = !data || data.errors > 0 || data.writes === 0;
  const unchanged = data ? data.entries.length - data.writes - data.errors : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Xem trước ${num(edits.length)} thay đổi`}
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button
            variant="primary"
            disabled={blocked}
            loading={apply.isPending}
            onClick={() =>
              apply.mutate(edits, {
                onSuccess: (res) => {
                  toast(
                    `Đã ghi ${res.applied} mục` +
                      (res.replacements.total
                        ? ` · thay ${res.replacements.total} chỗ trên ${res.replacements.chapters} chương.`
                        : "."),
                  );
                  onApplied();
                  onClose();
                },
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              })
            }
          >
            {data ? `Áp dụng ${num(data.writes)} thay đổi` : "Áp dụng"}
          </Button>
        </>
      }
    >
      {preview.isPending || !data ? (
        <Loading label="Đang đối chiếu" />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
            <Badge tone="celadon">{num(data.writes)} mục sẽ ghi</Badge>
            {data.errors > 0 ? <Badge tone="vermilion">{num(data.errors)} dòng lỗi</Badge> : null}
            {unchanged > 0 ? <Badge>{num(unchanged)} không đổi</Badge> : null}
          </div>

          {data.total_matches > 0 ? (
            <p className="mb-3 flex items-start gap-2 rounded-box border border-warning/40 bg-warning/10 px-2.5 py-2 text-[13px]">
              <IconWarning size={16} className="mt-0.5 shrink-0 text-warning" />
              <span>
                Đổi bản dịch Việt sẽ ghi đè cả nội dung ĐÃ DỊCH:{" "}
                <span data-numeric className="font-medium">
                  {num(data.total_matches)}
                </span>{" "}
                chỗ sẽ được thay theo. Không hoàn tác được.
              </span>
            </p>
          ) : null}

          {data.errors > 0 ? (
            <p className="mb-3 text-[13px] text-error">
              Sửa hoặc hoàn tác các dòng lỗi bên dưới rồi mở lại — còn lỗi thì cả đợt bị từ chối.
            </p>
          ) : null}

          <div className="overflow-x-auto">
            <table className="w-full min-w-[42rem] border-collapse text-left text-[13px]">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  {["", "Hán", "Việt", "Ghi chú", "Bản dịch cũ"].map((label, i) => (
                    <th
                      key={i}
                      className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.entries.map((row, i) => {
                  const kind = KIND_LABEL[row.kind];
                  return (
                    <tr
                      key={`${row.original_source}-${i}`}
                      className={clsx(
                        "border-b border-base-300 align-top last:border-b-0",
                        row.error && "bg-error/10",
                        !row.error && row.kind === "unchanged" && "opacity-50",
                      )}
                    >
                      <td className="w-24 px-2 py-1.5">
                        {row.error ? (
                          <Badge tone="vermilion">Lỗi</Badge>
                        ) : (
                          <Badge tone={kind.tone}>{kind.text}</Badge>
                        )}
                      </td>
                      <td className="px-2 py-1.5">
                        {row.kind === "rename" ? (
                          <>
                            <span className="opacity-50 line-through">{row.original_source}</span>
                            <span className="mx-1 opacity-40">→</span>
                          </>
                        ) : null}
                        <span className="font-medium">{row.source || "(trống)"}</span>
                      </td>
                      <td className="px-2 py-1.5">
                        {row.error ? (
                          <span className="text-error">{row.error}</span>
                        ) : (
                          <div className="flex flex-col gap-0.5">
                            {row.existing_target && row.existing_target !== row.target ? (
                              <DiffText
                                before={row.existing_target}
                                after={row.target}
                                mode="removed"
                                className="opacity-60"
                              />
                            ) : null}
                            <DiffText before={row.existing_target} after={row.target} className="font-medium" />
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-1.5 opacity-70">
                        {row.existing_note && row.existing_note !== row.note ? (
                          <span className="mr-1 opacity-60 line-through">{row.existing_note}</span>
                        ) : null}
                        {row.note || "—"}
                      </td>
                      <td className="w-32 px-2 py-1.5">
                        {row.count ? (
                          <span data-numeric className="text-warning">
                            {num(row.count)} chỗ / {num(row.chapters)} chương
                          </span>
                        ) : (
                          <span className="opacity-40">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}

/* ── Modal Trợ lý AI: dịch lại hàng loạt mục đã chọn ─────────────────── */

function AiAssistantModal({
  open,
  onClose,
  slug,
  sources,
  onStarted,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  sources: string[];
  onStarted: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const { data: settings } = useEbookSettings(slug);
  const run = useGlossaryAiRetranslate(slug);
  const toast = useToast();

  useEffect(() => {
    if (open) setInstruction("");
  }, [open]);

  const context = settings?.translate.context_note.trim() ?? "";
  const novel = settings?.novel;
  // Gửi kèm prompt để AI biết đang dịch truyện gì — hiện ra đây để khỏi đoán.
  const story = [
    { label: "Tên truyện", value: novel?.title ?? "" },
    { label: "Tác giả", value: novel?.author ?? "" },
    { label: "Giới thiệu", value: novel?.description ?? "" },
    { label: "Thể loại", value: settings?.translate.genre ?? "" },
  ].filter((row) => row.value.trim());

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Trợ lý AI dịch lại glossary"
      wide
      footer={
        <>
          <Button onClick={onClose}>Hủy</Button>
          <Button
            variant="primary"
            icon={<IconSparkle size={14} />}
            loading={run.isPending}
            disabled={sources.length === 0}
            onClick={() =>
              run.mutate(
                { sources, instruction: instruction.trim() },
                {
                  onSuccess: () => {
                    toast("Đã xếp vào hàng đợi — kết quả sẽ hiện ở đầu bảng để duyệt.");
                    onStarted();
                    onClose();
                  },
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                },
              )
            }
          >
            Nhờ AI xử lý {num(sources.length)} mục
          </Button>
        </>
      }
    >
      <p className="mb-3 text-[13px] opacity-70">
        AI rà soát <span data-numeric className="font-medium">{num(sources.length)}</span> mục đã chọn và đề
        xuất bản dịch đúng. Kết quả KHÔNG ghi đè: mục nào AI đổi sẽ vào hàng chờ duyệt (hàng vàng ở đầu
        bảng) kèm số chỗ ảnh hưởng, bạn duyệt từng mục hoặc hàng loạt.
      </p>
      <p className="mb-3 text-[13px] opacity-60">
        AI chỉ sửa cột Việt. Mục sai ở cột Hán (chip lọc “Hán lẫn Latin”, “Hán không có chữ Hán”) phải sửa
        tay trong bảng rồi bấm “Áp dụng” — các mục đó sẽ bị bỏ qua.
      </p>

      <div className="mb-3 rounded-box border border-base-300 p-2.5">
        <p className="mb-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
          Thông tin gửi kèm prompt
        </p>
        <dl className="grid gap-1 text-[13px]">
          {story.map((row) => (
            <div key={row.label} className="flex gap-2">
              <dt className="w-24 shrink-0 opacity-50">{row.label}</dt>
              <dd className="min-w-0 line-clamp-3 opacity-80">{row.value}</dd>
            </div>
          ))}
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 opacity-50">Mô tả bối cảnh</dt>
            <dd className="min-w-0 opacity-80">
              {context ? (
                <span className="whitespace-pre-wrap">{context}</span>
              ) : (
                <span className="opacity-70">
                  chưa có —{" "}
                  <Link to={`/ebooks/${slug}/settings`} className="link">
                    thêm ở Cài đặt → Dịch API
                  </Link>{" "}
                  để AI dịch sát hơn
                </span>
              )}
            </dd>
          </div>
        </dl>
      </div>

      <label className="text-[13px]">
        Yêu cầu thêm cho lần chạy này
        <Textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          className="mt-1 w-full"
          placeholder="vd: giữ nguyên cách gọi 'Đạo hữu', ưu tiên Hán Việt đậm cho tên công pháp"
        />
      </label>
    </Modal>
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
  const [activeFlags, setActiveFlags] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingSelected, setPendingSelected] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Drafts>({});
  const [addOpen, setAddOpen] = useState(false);
  const [ioOpen, setIoOpen] = useState(false);
  const [applyOpen, setApplyOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const toast = useToast();

  const filter = activeFlags.join(",");

  useEffect(() => setPage(1), [search, filter]);
  useEffect(() => setSelected(new Set()), [page, perPage, search, filter]);

  const { data, isPending, isFetching } = useGlossary(slug, {
    page,
    per_page: perPage,
    q: search,
    sort,
    dir,
    filter,
  });
  const { data: flagData } = useGlossaryFlags(slug);
  const { data: pending } = usePendingGlossary(slug);
  const clean = useCleanGlossary(slug);
  const bulkDelete = useDeleteGlossaryEntries(slug);
  const approvePending = useApprovePending(slug);
  const clearPending = useClearPending(slug);

  const edits = useMemo(() => Object.values(drafts), [drafts]);

  /* Callback ổn định để GlossaryRow (memo) không render lại khi dòng khác đổi. */
  const toggleRow = useCallback((source: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }, []);

  const editRow = useCallback((entry: GlossaryEntry, patch: Partial<GlossaryEntry>) => {
    setDrafts((prev) => {
      const current = prev[entry.source] ?? {
        source: entry.source,
        target: entry.target,
        note: entry.note,
        originalSource: entry.source,
      };
      const next = { ...current, ...patch };
      const rest = { ...prev };
      // Sửa rồi gõ lại đúng giá trị cũ thì không còn là thay đổi.
      if (sameValues(next, entry)) delete rest[entry.source];
      else rest[entry.source] = next;
      return rest;
    });
  }, []);

  const dropDraft = useCallback((source: string) => {
    setDrafts((prev) => {
      if (!(source in prev)) return prev;
      const rest = { ...prev };
      delete rest[source];
      return rest;
    });
  }, []);

  const toggleFlag = (key: string) =>
    setActiveFlags((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));

  const toggleSort = (col: string) => {
    if (sort === col) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(col);
      setDir("asc");
    }
  };

  const rows = data?.entries ?? [];
  const allChecked = rows.length > 0 && rows.every((r) => selected.has(r.source));
  // Đề xuất chờ duyệt CHƯA nằm trong glossary nên không qua bộ lọc được — ẩn
  // hẳn khi đang lọc, nếu không vài trăm hàng vàng che mất kết quả lọc.
  const pendingRows = page === 1 && !filter ? pending?.entries ?? [] : [];

  return (
    <Page
      title="Glossary"
      hint={`${slug} · tên riêng & thuật ngữ dùng cho prompt dịch — sửa trực tiếp trong bảng rồi bấm "Áp dụng" để xem trước cả đợt`}
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
          {/* Dính theo màn hình: sửa ở cuối bảng dài vẫn thấy nút Áp dụng. */}
          <div className="sticky top-12 z-20 mb-3 flex flex-wrap items-center gap-2 bg-base-100/95 py-1 backdrop-blur md:top-0">
            {edits.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2 rounded-box border border-warning/50 bg-warning/10 px-2.5 py-1.5">
                <span className="text-[13px] font-medium">
                  <span data-numeric>{num(edits.length)}</span> thay đổi chưa áp dụng
                </span>
                <Button size="sm" variant="ghost" icon={<IconRevert size={14} />} onClick={() => setDrafts({})}>
                  Hoàn tác tất cả
                </Button>
                <Button size="sm" variant="primary" onClick={() => setApplyOpen(true)}>
                  Áp dụng…
                </Button>
              </div>
            ) : null}

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

          {/* Lọc theo vị từ "giá trị nghi sai" — số trên chip là toàn glossary,
              không phải trang hiện tại. */}
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-0.5 inline-flex items-center gap-1.5 text-[13px] opacity-50">
              <IconFilter size={14} />
              Lọc mục nghi sai
            </span>
            {(flagData?.flags ?? []).map((flag) => {
              const active = activeFlags.includes(flag.key);
              return (
                <Button
                  key={flag.key}
                  size="sm"
                  variant={active ? "primary" : "neutral"}
                  disabled={flag.count === 0 && !active}
                  title={flag.hint}
                  onClick={() => toggleFlag(flag.key)}
                >
                  {flag.label}
                  <span data-numeric className={clsx("ml-1", !active && "opacity-50")}>
                    {num(flag.count)}
                  </span>
                </Button>
              );
            })}
            {activeFlags.length > 0 ? (
              <Button size="sm" variant="ghost" onClick={() => setActiveFlags([])}>
                Bỏ lọc
              </Button>
            ) : null}
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
                      <th className="w-24 px-2 py-1.5" />
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
                        draft={drafts[entry.source]}
                        slug={slug}
                        checked={selected.has(entry.source)}
                        onToggle={toggleRow}
                        onEdit={editRow}
                        onRevert={dropDraft}
                        onDeleted={dropDraft}
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
                <>
                  <Button
                    variant="primary"
                    icon={<IconSparkle size={14} />}
                    onClick={() => setAiOpen(true)}
                    title="Nhờ AI rà soát và dịch lại các mục đã chọn"
                  >
                    Trợ lý AI ({selected.size})
                  </Button>
                  <Button variant="danger" icon={<IconTrash size={14} />} onClick={() => setConfirmBulkDelete(true)}>
                    Xóa đã chọn ({selected.size})
                  </Button>
                </>
              ) : null}
            </SelectionBar>
          ) : null}
        </>
      ) : (
        <Panel className="overflow-hidden">
          <SuspectsView slug={slug} />
        </Panel>
      )}

      <AiAssistantModal
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        slug={slug}
        sources={[...selected]}
        onStarted={() => setSelected(new Set())}
      />
      <AddEntryModal open={addOpen} onClose={() => setAddOpen(false)} slug={slug} />
      <ExportImportModal open={ioOpen} onClose={() => setIoOpen(false)} slug={slug} />
      <ApplyEditsModal
        open={applyOpen}
        onClose={() => setApplyOpen(false)}
        slug={slug}
        edits={edits}
        onApplied={() => setDrafts({})}
      />
      <ConfirmDialog
        open={confirmBulkDelete}
        onCancel={() => setConfirmBulkDelete(false)}
        onConfirm={() =>
          bulkDelete.mutate([...selected], {
            onSuccess: () => {
              setConfirmBulkDelete(false);
              selected.forEach(dropDraft);
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
