import { useState } from "react";
import clsx from "clsx";

import {
  useAiFixNotes,
  useApplyNote,
  useChapterNotes,
  useDeleteNote,
  useDismissNote,
  useUpdateNote,
  type Note,
} from "@/lib/chapter";
import { Button, Spinner } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { IconClose, IconSparkle, IconTrash } from "@/components/icons";

const STATUS_LABEL: Record<Note["status"], string> = {
  open: "Đang chờ",
  resolved: "Đã sửa",
  dismissed: "Đã bỏ qua",
  stale: "Lệch bản dịch",
};

const STATUS_TONE: Record<Note["status"], "gold" | "celadon" | "neutral" | "vermilion"> = {
  open: "gold",
  resolved: "celadon",
  dismissed: "neutral",
  stale: "vermilion",
};

function NoteCard({
  note,
  slug,
  index,
  selected,
  onToggleSelect,
}: {
  note: Note;
  slug: string;
  index: number;
  selected: boolean;
  onToggleSelect: () => void;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState(note.note);
  const update = useUpdateNote(slug, index);
  const dismiss = useDismissNote(slug, index);
  const del = useDeleteNote(slug, index);
  const apply = useApplyNote(slug, index);

  return (
    <li className="rounded-box border border-base-300 p-2.5">
      <div className="flex items-start gap-2">
        {note.status === "open" ? (
          <Checkbox checked={selected} onChange={onToggleSelect} className="mt-0.5 shrink-0" />
        ) : null}
        <div className="min-w-0 flex-1">
          <blockquote className="line-clamp-2 border-l-2 border-base-300 pl-2 text-xs italic opacity-60">
            {note.selected_text}
          </blockquote>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={(e) => {
              const value = e.target.value;
              if (value !== note.note) update.mutate({ id: note.id, note: value });
            }}
            placeholder="Ghi chú của bạn về chỗ này…"
            rows={2}
            className="mt-1.5 w-full text-[13px]"
          />
        </div>
        <button
          type="button"
          onClick={() => del.mutate(note.id)}
          className="btn btn-ghost btn-xs btn-square shrink-0 text-error"
          aria-label="Xóa ghi chú"
        >
          <IconTrash size={13} />
        </button>
      </div>

      <div className="mt-1.5 flex items-center gap-1.5">
        <Badge tone={STATUS_TONE[note.status]}>{STATUS_LABEL[note.status]}</Badge>
        {note.status === "open" ? (
          <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(note.id)}>
            Bỏ qua
          </Button>
        ) : null}
      </div>

      {note.suggestion ? (
        <div className="mt-2 rounded-field bg-success/10 p-2">
          <p className="text-[13px]">{note.suggestion.fixed_text}</p>
          {note.suggestion.explanation ? (
            <p className="mt-1 text-xs opacity-60">{note.suggestion.explanation}</p>
          ) : null}
          <div className="mt-1.5 flex gap-1.5">
            <Button
              size="sm"
              variant="primary"
              loading={apply.isPending}
              onClick={() =>
                apply.mutate(note.id, {
                  onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Áp dụng
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

export function NotesPanel({
  open,
  onClose,
  slug,
  index,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  index: number;
}) {
  const { data: notes, isPending } = useChapterNotes(slug, index);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const aiFix = useAiFixNotes(slug, index);
  const toast = useToast();

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const runAiFix = () => {
    aiFix.mutate([...selected], {
      onSuccess: () => {
        setSelected(new Set());
        toast("Đã nhận đề xuất từ AI — xem trong từng ghi chú.");
      },
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Đóng ghi chú"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/30"
        />
      ) : null}
      <aside
        className={clsx(
          "fixed inset-y-0 right-0 z-50 flex w-96 max-w-[92vw] flex-col border-l border-base-300 bg-base-100 shadow-xl transition-transform",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-center justify-between border-b border-base-300 px-3 py-2.5">
          <h2 className="text-[13px] font-semibold">
            Ghi chú {notes ? <span data-numeric className="opacity-50">({notes.length})</span> : null}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-ghost btn-xs btn-square"
            aria-label="Đóng"
          >
            <IconClose size={14} />
          </button>
        </div>

        {selected.size > 0 ? (
          <div className="border-b border-base-300 p-2">
            <Button
              size="sm"
              variant="primary"
              icon={<IconSparkle size={14} />}
              loading={aiFix.isPending}
              onClick={runAiFix}
              className="w-full"
            >
              Sửa bằng AI ({selected.size})
            </Button>
          </div>
        ) : null}

        <div className="scroll-slim flex-1 overflow-y-auto p-2.5">
          {isPending ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : !notes || notes.length === 0 ? (
            <p className="py-8 text-center text-xs opacity-50">
              Chưa có ghi chú nào cho chương này. Bôi đen một đoạn văn bản để thêm ghi chú.
            </p>
          ) : (
            <ul className="space-y-2">
              {notes.map((note) => (
                <NoteCard
                  key={note.id}
                  note={note}
                  slug={slug}
                  index={index}
                  selected={selected.has(note.id)}
                  onToggleSelect={() => toggle(note.id)}
                />
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
}
