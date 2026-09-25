import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { useCurrentBook } from "@/lib/books";
import {
  applyPreview,
  fillContext,
  readSelectedThread,
  sendAssistantChat,
  useAssistantDefaults,
  useAssistantThread,
  useAssistantThreads,
  useCreateAssistantThread,
  useDeleteAssistantThread,
  usePatchAssistantThread,
  writeSelectedThread,
  type FindReplaceItem,
  type PreviewCard,
  type ToolTrace,
} from "@/lib/assistant";
import { ModelField, fetchAndMergeModels } from "@/components/AiProviderFields";
import { useAiProviders } from "@/lib/aiProviders";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { Loading } from "@/components/ui/Loading";
import { useToast } from "@/components/ui/Toast";
import { DiffText } from "@/components/DiffText";

const QUICK_CHIPS = [
  { label: "Dịch đoạn đang chọn", prompt: "Dịch đoạn đang chọn sang tiếng Việt, giữ nguyên cách chia đoạn." },
  { label: "Đề xuất glossary", prompt: "Đề xuất mục glossary mới từ đoạn đang chọn (Hán → Việt, kèm ghi chú ngắn)." },
  { label: "Tìm thay thông minh", prompt: "Tìm mọi biến thể của cụm cần thay trong đoạn đang chọn rồi đề xuất regex thay thế an toàn." },
  { label: "Trích nhân vật", prompt: "Trích nhân vật xuất hiện trong đoạn đang chọn (tên Hán, tên Việt gợi ý, vai trò, quan hệ)." },
] as const;

function chapterIndexFromPath(pathname: string): number | null {
  const m = pathname.match(/\/ebooks\/[^/]+\/chapters\/(\d+)/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

/** Tick chọn theo đoạn cho thẻ tìm-thay gộp: checkbox từng đoạn, nút Áp dụng
 * chỉ ghi các đoạn đã tick (gộp theo nhóm find/replace rồi gọi apply-batch). */
function FindReplacePicker({
  card,
  disabled,
  loading,
  onApply,
}: {
  card: PreviewCard;
  disabled: boolean;
  loading: boolean;
  onApply: (items: FindReplaceItem[]) => void;
}) {
  const items = card.items ?? [];
  const [ticked, setTicked] = useState<Set<number>>(() => new Set(items.map((_, i) => i)));

  const toggle = (i: number) => {
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  return (
    <div className="mt-1">
      <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto text-[12px]">
        {(card.groups ?? []).map((g, gi) => (
          <li key={gi} className="opacity-70">
            <code className="text-[11px]">{g.regex ? `/${g.find}/` : g.find}</code>
            {" → "}
            <code className="text-[11px]">{g.replace}</code>
            <span> ({g.count})</span>
          </li>
        ))}
      </ul>
      <ul className="mt-1 flex max-h-48 flex-col gap-1 overflow-y-auto">
        {items.map((it, i) => (
          <li key={i}>
            <label className="flex cursor-pointer items-start gap-1.5 rounded-field bg-base-100/70 p-1.5">
              <input
                type="checkbox"
                className="checkbox checkbox-xs mt-0.5"
                checked={ticked.has(i)}
                disabled={disabled}
                onChange={() => toggle(i)}
              />
              <span className="min-w-0 flex-1 text-[12px]">
                <span className="opacity-60">
                  C{it.chapter_index}·đ{it.para_index}{it.chapter_title ? ` · ${it.chapter_title}` : ""}:{" "}
                </span>
                <DiffText before={it.before} after={it.after} mode="added" />
              </span>
            </label>
          </li>
        ))}
      </ul>
      {card.truncated ? <p className="mt-0.5 text-[11px] opacity-60">Đã cắt ở 300 đoạn.</p> : null}
      <div className="mt-1.5">
        <Button
          size="sm"
          variant="primary"
          loading={loading}
          disabled={disabled || ticked.size === 0}
          onClick={() => onApply(items.filter((_, i) => ticked.has(i)))}
        >
          Áp dụng {ticked.size} đoạn
        </Button>
      </div>
    </div>
  );
}

export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const [slug] = useCurrentBook();
  const location = useLocation();
  const toast = useToast();

  const defaults = useAssistantDefaults(slug);
  const threadsQuery = useAssistantThreads(slug);
  const threads = useMemo(() => threadsQuery.data?.threads ?? [], [threadsQuery.data]);

  const [selectedId, setSelectedId] = useState<number | null>(() => readSelectedThread(slug));
  useEffect(() => setSelectedId(readSelectedThread(slug)), [slug]);
  useEffect(() => {
    if (!threads.length) return;
    if (selectedId && threads.some((t) => t.id === selectedId)) return;
    const first = threads[0].id;
    setSelectedId(first);
    writeSelectedThread(slug, first);
  }, [threads, selectedId, slug]);

  const pickThread = (id: number | null) => {
    setSelectedId(id);
    writeSelectedThread(slug, id);
  };

  const threadQuery = useAssistantThread(slug, selectedId);
  const thread = threadQuery.data?.thread ?? null;
  const messages = useMemo(() => threadQuery.data?.messages ?? [], [threadQuery.data]);

  const createThread = useCreateAssistantThread(slug);
  const patchThread = usePatchAssistantThread(slug, selectedId ?? 0);
  const deleteThread = useDeleteAssistantThread(slug);

  // Provider lấy từ mặc định (thread lúc tạo → ai.openai của ebook → global),
  // không cho đổi trong panel. Model đổi được theo thread, chỉ lưu vào thread.
  const baseUrl = thread?.provider_base_url ?? defaults.data?.provider_base_url ?? "";
  const { data: providerPresets } = useAiProviders();
  const providerName = useMemo(() => {
    const t = baseUrl.trim();
    if (!t) return "";
    return providerPresets?.presets.find((p) => p.base_url === t)?.name ?? "";
  }, [providerPresets, baseUrl]);
  const [model, setModel] = useState("");
  useEffect(() => {
    setModel(thread?.model ?? defaults.data?.model ?? "");
  }, [thread?.id, thread?.model, defaults.data]);

  const [modelsLoading, setModelsLoading] = useState(false);
  const refreshModels = async () => {
    setModelsLoading(true);
    try {
      const res = await fetchAndMergeModels(baseUrl, "");
      toast(res.error ?? `Đã nạp ${res.count} model mới (tổng ${res.total}).`, res.error ? "error" : "ok");
    } finally {
      setModelsLoading(false);
    }
  };

  const commitModel = (nextModel: string) => {
    if (!selectedId) return;
    patchThread.mutate({ model: nextModel });
  };

  // Thanh ngữ cảnh: slug + index chương + selection tự điền, sửa/tắt được.
  const [contextOn, setContextOn] = useState(true);
  const [chapterIndex, setChapterIndex] = useState<string>("");
  const [selection, setSelection] = useState("");
  const autoChapter = chapterIndexFromPath(location.pathname);
  useEffect(() => {
    setChapterIndex(autoChapter != null ? String(autoChapter) : "");
  }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  const grabSelection = () => {
    try {
      const text = window.getSelection()?.toString().trim() ?? "";
      if (text) setSelection(text.slice(0, 4000));
      else toast("Chưa bôi đen đoạn nào trên trang.", "error");
    } catch {
      toast("Không đọc được đoạn đang chọn.", "error");
    }
  };

  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [filling, setFilling] = useState(false);
  // Human-in-the-loop: trace + thẻ preview của lượt chat cuối (diff theo đoạn,
  // tick chọn rồi mới ghi qua nút Áp dụng).
  const [lastTrace, setLastTrace] = useState<ToolTrace[]>([]);
  const [previews, setPreviews] = useState<PreviewCard[]>([]);
  const [applying, setApplying] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const ensureThread = async (): Promise<number | null> => {
    if (selectedId) return selectedId;
    try {
      const res = await createThread.mutateAsync({
        provider_base_url: baseUrl || defaults.data?.provider_base_url || "",
        model: model || defaults.data?.model || "",
      });
      pickThread(res.thread.id);
      return res.thread.id;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
      return null;
    }
  };

  const send = async (text?: string) => {
    const content = (text ?? draft).trim();
    if (!content || sending) return;
    if (!slug) {
      toast("Mở một truyện trước khi chat.", "error");
      return;
    }
    const threadId = await ensureThread();
    if (!threadId) return;
    setSending(true);
    try {
      const chapterNum = chapterIndex.trim() === "" ? null : Number(chapterIndex);
      const res = await sendAssistantChat(slug, threadId, {
        content,
        chapter_index: Number.isFinite(chapterNum) ? chapterNum : null,
        selection: contextOn ? selection.trim() : "",
      });
      setDraft("");
      setLastTrace(res.tool_calls ?? []);
      setPreviews(res.previews ?? []);
      await threadQuery.refetch();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setSending(false);
    }
  };

  const refreshAfterApply = () => {
    // Bản dịch/glossary đổi → làm mới nội dung chương đang hiển thị.
    queryClient.invalidateQueries({ queryKey: ["chapter"] });
    queryClient.invalidateQueries({ queryKey: ["chapters"] });
    queryClient.invalidateQueries({ queryKey: ["book-search"] });
    queryClient.invalidateQueries({ queryKey: ["glossary"] });
  };

  const applyCard = async (idx: number) => {
    const card = previews[idx];
    if (!card || applying != null) return;
    setApplying(idx);
    try {
      await applyPreview(slug, card.apply.endpoint, card.apply.body);
      toast("Đã áp dụng.");
      setPreviews((prev) => prev.filter((_, i) => i !== idx));
      refreshAfterApply();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setApplying(null);
    }
  };

  const applyFindReplace = async (idx: number, items: FindReplaceItem[]) => {
    const card = previews[idx];
    if (!card || applying != null || items.length === 0) return;
    // Gộp đoạn đã tick theo nhóm find/replace → selections kèm expected.
    const byGroup = new Map<number, FindReplaceItem[]>();
    for (const it of items) {
      const list = byGroup.get(it.group) ?? [];
      list.push(it);
      byGroup.set(it.group, list);
    }
    const groups = (card.groups ?? []).flatMap((g, gi) => {
      const list = byGroup.get(gi) ?? [];
      if (!list.length) return [];
      return [{
        find: g.find,
        replace: g.replace,
        regex: g.regex,
        selections: list.map((it) => ({
          chapter_index: it.chapter_index,
          para_index: it.para_index,
          expected: it.before,
        })),
      }];
    });
    if (!groups.length) return;
    setApplying(idx);
    try {
      const res = (await applyPreview(slug, "find-replace/apply-batch", {
        groups,
        source: card.source ?? "translated",
        all_matches: false,
      })) as { replaced?: number; stale?: number };
      toast(`Đã thay ${res.replaced ?? 0} chỗ${res.stale ? ` (${res.stale} đoạn đã đổi, bỏ qua)` : ""}.`);
      setPreviews((prev) => prev.filter((_, i) => i !== idx));
      refreshAfterApply();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setApplying(null);
    }
  };

  const newChat = async () => {
    if (!slug) return;
    try {
      const res = await createThread.mutateAsync({
        provider_base_url: baseUrl || defaults.data?.provider_base_url || "",
        model: model || defaults.data?.model || "",
      });
      pickThread(res.thread.id);
      setDraft("");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const removeThread = async () => {
    if (!selectedId) return;
    if (!window.confirm("Xóa đoạn chat này?")) return;
    try {
      await deleteThread.mutateAsync(selectedId);
      pickThread(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <div className="flex h-full flex-col bg-base-100">
      <header className="flex items-center gap-2 border-b border-base-300 px-3 py-2">
        <span className="font-display text-sm font-semibold">Trợ lý</span>
        {slug ? (
          <span className="badge badge-ghost badge-xs max-w-32 truncate" title={slug}>
            {slug}
          </span>
        ) : null}
        <span className="ml-auto" />
        <Button size="sm" variant="ghost" onClick={newChat} loading={createThread.isPending} title="Đoạn chat mới">
          +
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose} title="Đóng panel trợ lý" aria-label="Đóng panel trợ lý">
          ✕
        </Button>
      </header>

      {!slug ? (
        <div className="flex flex-1 items-center justify-center p-4 text-center text-sm opacity-60">
          Mở một truyện trong Thư viện để dùng trợ lý trong phạm vi ebook đó.
        </div>
      ) : (
        <>
          <div className="border-b border-base-300 px-3 py-2">
            {defaults.isLoading ? (
              <Loading size="sm" label="Đang nạp provider" />
            ) : (
              <div className="flex flex-col gap-1">
                <p className="px-1 text-[11px] opacity-60" title={baseUrl}>
                  Provider:{" "}
                  <span className="font-medium opacity-100">
                    {providerName || (baseUrl ? baseUrl : "chưa cấu hình")}
                  </span>
                  {providerName && baseUrl ? <span className="opacity-70"> · {baseUrl}</span> : null}
                </p>
                <ModelField
                  label="Model"
                  value={model}
                  baseUrl={baseUrl}
                  onChange={(v) => {
                    const next = String(v ?? "");
                    setModel(next);
                    commitModel(next);
                  }}
                />
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={refreshModels} loading={modelsLoading}>
                    Tải models
                  </Button>
                  {defaults.data && !defaults.data.api_key_configured ? (
                    <span className="text-[11px] text-warning">Chưa cấu hình API key (Cài đặt → Provider AI).</span>
                  ) : null}
                </div>
              </div>
            )}
            {threads.length > 0 ? (
              <div className="mt-1 flex items-center gap-1.5">
                <Select
                  className="min-w-0 flex-1"
                  value={selectedId ?? ""}
                  onChange={(e) => pickThread(e.target.value ? Number(e.target.value) : null)}
                  aria-label="Đoạn chat"
                >
                  <option value="">— chọn đoạn chat —</option>
                  {threads.map((t) => (
                    <option key={t.id} value={t.id}>
                      #{t.id} · {t.model || "chưa chọn model"}
                    </option>
                  ))}
                </Select>
                <Button size="sm" variant="ghost" onClick={removeThread} title="Xóa đoạn chat">
                  🗑
                </Button>
              </div>
            ) : null}
          </div>

          <div className="border-b border-base-300 px-3 py-2">
            <label className="flex cursor-pointer items-center gap-2 text-xs">
              <input
                type="checkbox"
                className="checkbox checkbox-xs"
                checked={contextOn}
                onChange={(e) => setContextOn(e.target.checked)}
              />
              <span className="opacity-70">Gắn ngữ cảnh (chương + đoạn chọn)</span>
            </label>
            {contextOn ? (
              <div className="mt-1.5 flex flex-col gap-1.5">
                <div className="flex items-center gap-1.5">
                  <Input
                    className="w-24"
                    inputMode="numeric"
                    placeholder="Chương"
                    value={chapterIndex}
                    onChange={(e) => setChapterIndex(e.target.value)}
                    aria-label="Index chương"
                  />
                  <Button size="sm" variant="ghost" onClick={grabSelection}>
                    Lấy đoạn đang chọn
                  </Button>
                  {selection ? (
                    <Button size="sm" variant="ghost" onClick={() => setSelection("")}>
                      Xóa
                    </Button>
                  ) : null}
                </div>
                <Textarea
                  rows={2}
                  placeholder="Đoạn đang chọn (tự điền khi bôi đen + bấm nút)…"
                  value={selection}
                  onChange={(e) => setSelection(e.target.value)}
                />
              </div>
            ) : null}
          </div>

          <div className="scroll-slim flex-1 overflow-y-auto px-3 py-2">
            {threadQuery.isLoading ? (
              <Loading size="sm" label="Đang nạp hội thoại" />
            ) : messages.length === 0 ? (
              <p className="py-6 text-center text-[13px] opacity-55">
                Chưa có tin nhắn. Hỏi về chương đang mở, glossary, nhân vật…
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {messages.map((m) => (
                  <li
                    key={m.id}
                    className={clsx(
                      "chat",
                      m.role === "user" ? "chat-end" : "chat-start",
                    )}
                  >
                    <div
                      className={clsx(
                        "chat-bubble max-w-full text-[13px] whitespace-pre-wrap",
                        m.role === "user" ? "chat-bubble-primary" : "chat-bubble-neutral",
                      )}
                    >
                      {m.content}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {lastTrace.length > 0 ? (
            <div className="flex flex-wrap gap-1 px-3 pb-1">
              {lastTrace.map((t, i) => (
                <span
                  key={i}
                  className={clsx("badge badge-xs", t.ok ? "badge-ghost" : "badge-error badge-soft")}
                  title={JSON.stringify(t.arguments)}
                >
                  {t.ok ? "✓" : "✕"} {t.name}
                </span>
              ))}
            </div>
          ) : null}

          {previews.map((card, idx) => (
            <div key={idx} className="mx-3 mb-2 rounded-box border border-primary/30 bg-primary/5 p-2">
              <p className="text-xs font-medium">Đề xuất: {card.title}</p>
              {card.kind === "paragraph" ? (
                <div className="mt-1 flex flex-col gap-1 text-[12px]">
                  <DiffText before={card.before ?? ""} after={card.after ?? ""} mode="removed" />
                  <DiffText before={card.before ?? ""} after={card.after ?? ""} mode="added" />
                  {card.deleted ? (
                    <span className="text-warning">Áp dụng sẽ XÓA đoạn này.</span>
                  ) : null}
                </div>
              ) : card.kind === "find_replace" ? (
                <FindReplacePicker
                  card={card}
                  disabled={applying != null}
                  loading={applying === idx}
                  onApply={(items) => void applyFindReplace(idx, items)}
                />
              ) : (
                <ul className="mt-1 flex max-h-40 flex-col gap-0.5 overflow-y-auto text-[12px]">
                  {(card.entries ?? []).map((e, i) => (
                    <li key={i} className={clsx(e.error && "text-error")}>
                      {e.source} → {e.target}
                      <span className="opacity-60"> ({e.kind}{e.error ? `: ${e.error}` : ""})</span>
                    </li>
                  ))}
                  {card.entries_truncated ? <li className="opacity-60">…</li> : null}
                </ul>
              )}
              {card.kind === "find_replace" ? null : (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="primary"
                    loading={applying === idx}
                    disabled={applying != null || card.has_errors}
                    onClick={() => void applyCard(idx)}
                    title={card.has_errors ? "Còn dòng lỗi — sửa lại trước khi áp dụng" : "Ghi đề xuất này"}
                  >
                    Áp dụng
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setPreviews((p) => p.filter((_, i) => i !== idx))}>
                    Bỏ qua
                  </Button>
                </div>
              )}
            </div>
          ))}

          <div className="flex items-center gap-1.5 px-3 pb-2">
            <Button
              size="sm"
              variant="ghost"
              loading={filling}
              onClick={() => {
                const chapterNum = chapterIndex.trim() === "" ? null : Number(chapterIndex);
                setFilling(true);
                fillContext(slug, {
                  chapter_indexes:
                    contextOn && Number.isFinite(chapterNum) && chapterNum != null
                      ? [chapterNum]
                      : [],
                  model_override: model,
                })
                  .then(() => toast("Đã xếp job fill ngữ cảnh — theo dõi ở Hàng đợi."))
                  .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"))
                  .finally(() => setFilling(false));
              }}
              title="Dò tên riêng, AI dịch lại glossary và trích nhân vật bằng job nền"
            >
              Fill ngữ cảnh
            </Button>
            <Link to="/queue" className="link link-hover text-xs opacity-70">
              Xem hàng đợi
            </Link>
          </div>

          <div className="border-t border-base-300 px-3 py-2">
            <div className="flex flex-wrap gap-1.5 pb-2">
              {QUICK_CHIPS.map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  className="badge badge-outline cursor-pointer py-2.5 text-[11px] hover:badge-primary"
                  onClick={() => setDraft(chip.prompt)}
                >
                  {chip.label}
                </button>
              ))}
            </div>
            <div className="join w-full">
              <Textarea
                className="join-item min-w-0 flex-1"
                rows={2}
                placeholder="Hỏi trợ lý trong phạm vi truyện này…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <Button
                className="join-item"
                variant="primary"
                loading={sending}
                disabled={!draft.trim()}
                onClick={() => void send()}
              >
                Gửi
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
