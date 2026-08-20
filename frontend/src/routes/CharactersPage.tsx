import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { num } from "@/lib/format";
import {
  useApprovePending,
  useCharacters,
  useCharactersPending,
  useClearPending,
  useDeleteCharacters,
  useDeleteRelation,
  useUpsertCharacter,
  useUpsertRelation,
  type CharacterEntry,
  type Relation,
} from "@/lib/characters";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { Checkbox, Input, InputWithIcon, Select } from "@/components/ui/Field";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { IconChevronRight, IconPlus, IconSearch, IconTrash } from "@/components/icons";

const cellInput =
  "input input-xs w-full border-transparent bg-transparent hover:border-base-300 focus:border-primary";

const IMPORTANCE_OPTIONS = [
  { value: "main", label: "Chính" },
  { value: "side", label: "Phụ" },
  { value: "minor", label: "Thoáng qua" },
];

/* ── Quan hệ của một nhân vật (mở rộng dưới hàng) ────────────────────── */

function RelationRow({ a, r, slug }: { a: string; r: Relation; slug: string }) {
  const del = useDeleteRelation(slug);
  const toast = useToast();
  return (
    <tr className="border-b border-base-300/60 text-[12px] last:border-b-0">
      <td className="py-1 pr-2 pl-8" data-numeric>
        {r.from_chapter}
        {r.to_chapter ? `–${r.to_chapter}` : "+"}
      </td>
      <td className="py-1 pr-2 font-medium">
        {r.b_source}
        {r.b_target ? <span className="ml-1 opacity-50">({r.b_target})</span> : null}
      </td>
      <td className="py-1 pr-2 opacity-70">{r.a_calls_b || "—"}</td>
      <td className="py-1 pr-2 opacity-70">{r.a_self || "—"}</td>
      <td className="py-1 pr-2 opacity-50">{r.note || "—"}</td>
      <td className="py-1 pr-2 text-right">
        <button
          type="button"
          onClick={() =>
            del.mutate(
              { a_source: a, b_source: r.b_source, from_chapter: r.from_chapter },
              { onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") },
            )
          }
          className="btn btn-ghost btn-xs text-error"
        >
          Xóa
        </button>
      </td>
    </tr>
  );
}

function AddRelationForm({ a, slug, allSources }: { a: string; slug: string; allSources: string[] }) {
  const [b, setB] = useState("");
  const [fromChapter, setFromChapter] = useState("0");
  const [aCallsB, setACallsB] = useState("");
  const [aSelf, setASelf] = useState("");
  const [note, setNote] = useState("");
  const upsert = useUpsertRelation(slug);
  const toast = useToast();

  const submit = () => {
    if (!b.trim()) {
      toast("Cần chọn nhân vật B.", "error");
      return;
    }
    upsert.mutate(
      {
        a_source: a,
        b_source: b.trim(),
        from_chapter: Number(fromChapter) || 0,
        a_calls_b: aCallsB.trim(),
        a_self: aSelf.trim(),
        note: note.trim(),
      },
      {
        onSuccess: () => {
          setB("");
          setFromChapter("0");
          setACallsB("");
          setASelf("");
          setNote("");
        },
        onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
      },
    );
  };

  return (
    <tr className="border-b border-base-300/60 text-[12px]">
      <td className="py-1 pr-2 pl-8">
        <Input
          value={fromChapter}
          onChange={(e) => setFromChapter(e.target.value)}
          className="input-xs w-16"
          placeholder="0"
        />
      </td>
      <td className="py-1 pr-2">
        <Input
          value={b}
          onChange={(e) => setB(e.target.value)}
          list={`chars-${a}`}
          placeholder="B (tên gốc)"
          className="input-xs w-32"
        />
        <datalist id={`chars-${a}`}>
          {allSources.filter((s) => s !== a).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </td>
      <td className="py-1 pr-2">
        <Input value={aCallsB} onChange={(e) => setACallsB(e.target.value)} placeholder="A gọi B" className="input-xs w-24" />
      </td>
      <td className="py-1 pr-2">
        <Input value={aSelf} onChange={(e) => setASelf(e.target.value)} placeholder="A tự xưng" className="input-xs w-24" />
      </td>
      <td className="py-1 pr-2">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ghi chú" className="input-xs w-32" />
      </td>
      <td className="py-1 pr-2 text-right">
        <Button size="sm" variant="primary" loading={upsert.isPending} onClick={submit}>
          Thêm
        </Button>
      </td>
    </tr>
  );
}

/* ── Một hàng nhân vật ───────────────────────────────────────────────── */

function CharacterRow({
  entry,
  checked,
  onToggle,
  slug,
  allSources,
}: {
  entry: CharacterEntry;
  checked: boolean;
  onToggle: () => void;
  slug: string;
  allSources: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState(entry);
  const upsert = useUpsertCharacter(slug);
  const toast = useToast();

  useEffect(() => setDraft(entry), [entry]);

  const save = (patch: Partial<CharacterEntry>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    if (
      next.source === entry.source &&
      next.target === entry.target &&
      next.aliases === entry.aliases &&
      next.gender === entry.gender &&
      next.self_pronoun === entry.self_pronoun &&
      next.narrator_ref === entry.narrator_ref &&
      next.role_note === entry.role_note &&
      next.importance === entry.importance
    ) {
      return;
    }
    if (!next.source.trim()) return;
    upsert.mutate(
      { ...next, originalSource: entry.source },
      { onError: (err) => toast(err instanceof Error ? err.message : String(err), "error") },
    );
  };

  return (
    <>
      <tr className={clsx("border-b border-base-300 last:border-b-0", checked && "bg-warning/5")}>
        <td className="w-8 px-2 py-1">
          <Checkbox checked={checked} onChange={onToggle} />
        </td>
        <td className="w-8 px-1 py-1">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="btn btn-ghost btn-xs btn-square"
            aria-label="Quan hệ"
          >
            <IconChevronRight size={12} className={clsx("transition-transform", expanded && "rotate-90")} />
          </button>
        </td>
        <td className="px-1 py-1">
          <Input
            value={draft.source}
            onChange={(e) => setDraft({ ...draft, source: e.target.value })}
            onBlur={(e) => save({ source: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="px-1 py-1">
          <Input
            value={draft.target}
            onChange={(e) => setDraft({ ...draft, target: e.target.value })}
            onBlur={(e) => save({ target: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="px-1 py-1">
          <Input
            value={draft.aliases}
            onChange={(e) => setDraft({ ...draft, aliases: e.target.value })}
            onBlur={(e) => save({ aliases: e.target.value.trim() })}
            placeholder="a|b|c"
            className={cellInput}
          />
        </td>
        <td className="w-20 px-1 py-1">
          <Input
            value={draft.gender}
            onChange={(e) => setDraft({ ...draft, gender: e.target.value })}
            onBlur={(e) => save({ gender: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="w-24 px-1 py-1">
          <Input
            value={draft.self_pronoun}
            onChange={(e) => setDraft({ ...draft, self_pronoun: e.target.value })}
            onBlur={(e) => save({ self_pronoun: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="w-24 px-1 py-1">
          <Input
            value={draft.narrator_ref}
            onChange={(e) => setDraft({ ...draft, narrator_ref: e.target.value })}
            onBlur={(e) => save({ narrator_ref: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="px-1 py-1">
          <Input
            value={draft.role_note}
            onChange={(e) => setDraft({ ...draft, role_note: e.target.value })}
            onBlur={(e) => save({ role_note: e.target.value.trim() })}
            className={cellInput}
          />
        </td>
        <td className="w-24 px-1 py-1">
          <Select
            value={draft.importance}
            onChange={(e) => save({ importance: e.target.value })}
            className="select-xs w-full"
          >
            {IMPORTANCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-base-300 bg-base-200/30 last:border-b-0">
          <td colSpan={9} className="px-2 py-1.5">
            <table className="w-full">
              <tbody>
                {entry.relations.map((r) => (
                  <RelationRow key={`${r.b_source}-${r.from_chapter}`} a={entry.source} r={r} slug={slug} />
                ))}
                <AddRelationForm a={entry.source} slug={slug} allSources={allSources} />
              </tbody>
            </table>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/* ── Modal thêm nhân vật ─────────────────────────────────────────────── */

function AddCharacterModal({ open, onClose, slug }: { open: boolean; onClose: () => void; slug: string }) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const upsert = useUpsertCharacter(slug);
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setSource("");
      setTarget("");
    }
  }, [open]);

  const submit = () => {
    if (!source.trim()) {
      toast("Cần tên gốc.", "error");
      return;
    }
    upsert.mutate(
      {
        source: source.trim(),
        target: target.trim(),
        aliases: "",
        gender: "",
        self_pronoun: "",
        narrator_ref: "",
        role_note: "",
        importance: "side",
        originalSource: "",
      },
      {
        onSuccess: () => {
          toast("Đã thêm — điền tiếp chi tiết ngay trong bảng.");
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
      title="Thêm nhân vật"
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
          Tên gốc
          <Input autoFocus value={source} onChange={(e) => setSource(e.target.value)} className="mt-1 w-full" />
        </label>
        <label className="text-[13px]">
          Tên Việt
          <Input value={target} onChange={(e) => setTarget(e.target.value)} className="mt-1 w-full" />
        </label>
      </div>
    </Modal>
  );
}

/* ── Tab Đề xuất ─────────────────────────────────────────────────────── */

function PendingTab({ slug }: { slug: string }) {
  const { data, isPending } = useCharactersPending(slug);
  const [selChars, setSelChars] = useState<Set<string>>(new Set());
  const [selRels, setSelRels] = useState<Set<number>>(new Set());
  const approve = useApprovePending(slug);
  const clear = useClearPending(slug);
  const toast = useToast();

  useEffect(() => {
    setSelChars(new Set());
    setSelRels(new Set());
  }, [data]);

  if (isPending) {
    return (
      <Loading label="Đang tải nhân vật" />
    );
  }
  const characters = data?.characters ?? [];
  const relations = data?.relations ?? [];

  const approveSelected = () => {
    const chars = characters.filter((c) => selChars.has(c.source));
    const rels = relations.filter((_, i) => selRels.has(i));
    if (chars.length === 0 && rels.length === 0) {
      toast("Chưa chọn đề xuất nào.", "error");
      return;
    }
    approve.mutate(
      { characters: chars, relations: rels },
      {
        onSuccess: (res) => {
          toast(
            `Đã duyệt ${res.approved_characters} nhân vật, ${res.approved_relations} quan hệ.` +
              (res.blocked.length ? ` ${res.blocked.length} quan hệ bị chặn.` : ""),
            res.blocked.length ? "error" : "ok",
          );
        },
      },
    );
  };

  return (
    <div className="space-y-5 p-3">
      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <h3 className="text-[13px] font-semibold">Nhân vật ({characters.length})</h3>
          <div className="ml-auto flex gap-1.5">
            <Button
              size="sm"
              disabled={selChars.size === 0}
              onClick={() => clear.mutate({ characters: [...selChars] })}
            >
              Bỏ đã chọn
            </Button>
          </div>
        </div>
        {characters.length === 0 ? (
          <p className="py-2 text-xs opacity-50">Không có đề xuất nhân vật nào.</p>
        ) : (
          <div className="overflow-x-auto rounded-box border border-base-300">
            <table className="w-full min-w-[40rem] border-collapse text-left text-[12px]">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  <th className="w-8 px-2 py-1.5" />
                  <th className="px-2 py-1.5">Tên gốc</th>
                  <th className="px-2 py-1.5">Tên Việt</th>
                  <th className="px-2 py-1.5">Alias</th>
                  <th className="px-2 py-1.5">Giới</th>
                </tr>
              </thead>
              <tbody>
                {characters.map((c) => (
                  <tr key={c.source} className="border-b border-base-300 last:border-b-0">
                    <td className="px-2 py-1">
                      <Checkbox
                        checked={selChars.has(c.source)}
                        onChange={() =>
                          setSelChars((prev) => {
                            const next = new Set(prev);
                            if (next.has(c.source)) next.delete(c.source);
                            else next.add(c.source);
                            return next;
                          })
                        }
                      />
                    </td>
                    <td className="px-2 py-1 font-medium">
                      {c.source} {c.update_only ? <Badge tone="indigo">cập nhật</Badge> : null}
                    </td>
                    <td className="px-2 py-1">{c.target || "—"}</td>
                    <td className="px-2 py-1 opacity-60">{(c.aliases_raw ?? c.new_aliases_raw ?? []).join(" | ") || "—"}</td>
                    <td className="px-2 py-1 opacity-60">{c.gender || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <h3 className="text-[13px] font-semibold">Quan hệ ({relations.length})</h3>
          <div className="ml-auto flex gap-1.5">
            <Button
              size="sm"
              disabled={selRels.size === 0}
              onClick={() => clear.mutate({ relations: relations.filter((_, i) => selRels.has(i)) })}
            >
              Bỏ đã chọn
            </Button>
          </div>
        </div>
        {relations.length === 0 ? (
          <p className="py-2 text-xs opacity-50">Không có đề xuất quan hệ nào.</p>
        ) : (
          <ul className="space-y-1.5">
            {relations.map((r, i) => (
              <li key={i} className="rounded-box border border-base-300 p-2 text-[12px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Checkbox
                    checked={selRels.has(i)}
                    onChange={() =>
                      setSelRels((prev) => {
                        const next = new Set(prev);
                        if (next.has(i)) next.delete(i);
                        else next.add(i);
                        return next;
                      })
                    }
                  />
                  <span className="font-medium">
                    {r.a_source} → {r.b_source}
                  </span>
                  <span data-numeric className="opacity-50">
                    từ chương {r.from_chapter ?? 0}
                  </span>
                  {r.inferred ? <Badge tone="gold">suy luận</Badge> : null}
                  {r.confidence ? <Badge tone="neutral">{r.confidence}</Badge> : null}
                </div>
                <p className="mt-1 opacity-70">
                  gọi <strong>{r.a_calls_b_vi || "—"}</strong> · tự xưng <strong>{r.a_self_vi || "—"}</strong>
                </p>
                {r.evidence ? <p className="mt-1 border-l-2 border-base-300 pl-2 italic opacity-50">{r.evidence}</p> : null}
                {r.reason ? <p className="mt-0.5 opacity-50">{r.reason}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center gap-2 border-t border-base-300 pt-3">
        <Button variant="primary" loading={approve.isPending} onClick={approveSelected}>
          Duyệt đã chọn
        </Button>
        <Button
          variant="danger"
          disabled={characters.length === 0 && relations.length === 0}
          onClick={() => clear.mutate({ all: true })}
        >
          Bỏ tất cả đề xuất
        </Button>
      </div>
    </div>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function CharactersPage() {
  const { slug = "" } = useParams();
  const [tab, setTab] = useState<"table" | "pending">("table");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);

  const { data, isPending } = useCharacters(slug);
  const { data: pending } = useCharactersPending(slug);
  const bulkDelete = useDeleteCharacters(slug);

  const entries = data?.entries ?? [];
  const allSources = useMemo(() => entries.map((e) => e.source), [entries]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) =>
        e.source.toLowerCase().includes(q) ||
        e.target.toLowerCase().includes(q) ||
        e.aliases.toLowerCase().includes(q),
    );
  }, [entries, search]);

  const allChecked = filtered.length > 0 && filtered.every((e) => selected.has(e.source));
  const pendingCount = (pending?.counts.characters ?? 0) + (pending?.counts.relations ?? 0);

  return (
    <Page
      title="Nhân vật"
      hint={`${slug} · bảng nhân vật + quan hệ có hướng — bấm mũi tên để mở quan hệ, sửa trực tiếp trong bảng`}
      actions={
        <div role="tablist" className="tabs tabs-box tabs-sm">
          <button
            role="tab"
            type="button"
            className={clsx("tab", tab === "table" && "tab-active")}
            onClick={() => setTab("table")}
          >
            Bảng nhân vật
          </button>
          <button
            role="tab"
            type="button"
            className={clsx("tab", tab === "pending" && "tab-active")}
            onClick={() => setTab("pending")}
          >
            Đề xuất {pendingCount > 0 ? `(${pendingCount})` : ""}
          </button>
        </div>
      }
    >
      {tab === "table" ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <InputWithIcon
              icon={<IconSearch size={14} />}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm tên gốc / tên Việt / alias"
              className="w-64"
            />
            <span data-numeric className="text-[13px] opacity-60">
              {num(filtered.length)} nhân vật
            </span>
            <div className="ml-auto flex gap-2">
              {selected.size > 0 ? (
                <Button variant="danger" icon={<IconTrash size={14} />} onClick={() => setConfirmBulkDelete(true)}>
                  Xóa đã chọn ({selected.size})
                </Button>
              ) : null}
              <Button icon={<IconPlus size={14} />} variant="primary" onClick={() => setAddOpen(true)}>
                Thêm nhân vật
              </Button>
            </div>
          </div>

          <Panel className="overflow-hidden">
            {isPending ? (
              <SkeletonTable rows={6} cols={4} />
            ) : filtered.length === 0 ? (
              <EmptyState
                title={search ? "Không có nhân vật nào khớp" : "Chưa có nhân vật nào"}
                hint={search ? "Thử từ khóa khác." : 'Bấm "Thêm nhân vật", hoặc dùng "AI trích nhân vật" ở trang truyện.'}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[64rem] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-base-300 bg-base-200/60">
                      <th className="w-8 px-2 py-1.5">
                        <Checkbox
                          checked={allChecked}
                          onChange={() =>
                            setSelected((prev) => {
                              const next = new Set(prev);
                              filtered.forEach((e) => (allChecked ? next.delete(e.source) : next.add(e.source)));
                              return next;
                            })
                          }
                        />
                      </th>
                      <th className="w-8" />
                      {["Tên gốc", "Tên Việt", "Alias", "Giới", "Tự xưng", "Lời kể gọi", "Vai trò", "Mức độ"].map(
                        (h) => (
                          <th
                            key={h}
                            className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
                          >
                            {h}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((entry) => (
                      <CharacterRow
                        key={entry.source}
                        entry={entry}
                        slug={slug}
                        allSources={allSources}
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
        </>
      ) : (
        <Panel className="overflow-hidden">
          <PendingTab slug={slug} />
        </Panel>
      )}

      <AddCharacterModal open={addOpen} onClose={() => setAddOpen(false)} slug={slug} />
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
        title="Xóa nhân vật đã chọn"
        body={`Xóa ${selected.size} nhân vật đã chọn? Quan hệ liên quan cũng bị xóa theo. Không thể hoàn tác.`}
        confirmLabel="Xóa"
        destructive
        pending={bulkDelete.isPending}
      />
    </Page>
  );
}
