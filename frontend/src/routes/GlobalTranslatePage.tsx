import { useEffect, useState } from "react";

import { Page } from "@/app/Shell";
import {
  useSaveTranslateDefaults,
  useTranslateDefaults,
  type TranslateDefaults,
} from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

/**
 * Trang DỊCH CHUNG — cấu hình mặc định của khâu dịch cho TOÀN HỆ THỐNG
 * (defaults.translate): prompt, thể loại/văn phong, giới hạn prompt (token/
 * chars), chunk, retry, glossary và dọn chữ Hán. Từng truyện vẫn ghi đè được ở
 * Cài đặt → Dịch; provider/key nằm ở Global AI; Local MT có trang riêng.
 */
export function GlobalTranslatePage() {
  const toast = useToast();
  const { data, isPending, error } = useTranslateDefaults();
  const save = useSaveTranslateDefaults();
  const [draft, setDraft] = useState<TranslateDefaults | null>(null);
  const [promptFullscreen, setPromptFullscreen] = useState(false);

  useEffect(() => {
    if (data) setDraft({ ...data });
  }, [data]);

  const dirty = draft != null && data != null && JSON.stringify(draft) !== JSON.stringify(data);

  if (isPending) {
    return (
      <Page title="Dịch chung" loading loadingLabel="Đang đọc cấu hình dịch">
        {null}
      </Page>
    );
  }

  if (error || !data || !draft) {
    return (
      <Page title="Không mở được cấu hình dịch">
        <Panel>
          <EmptyState
            title="Không đọc được cấu hình dịch chung"
            hint={error instanceof Error ? error.message : String(error)}
          />
        </Panel>
      </Page>
    );
  }

  const set = <K extends keyof TranslateDefaults>(key: K, value: TranslateDefaults[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  return (
    <Page
      title="Dịch chung"
      hint="Cấu hình khâu dịch dùng cho mọi truyện chưa có cấu hình riêng — từng truyện vẫn ghi đè được ở Cài đặt → Dịch"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-base-300 pb-3 text-[13px]">
        <Badge tone="indigo">defaults.translate</Badge>
        <span className="opacity-70">Provider & API key quản lý ở Global AI; Local MT có trang riêng.</span>
        <div className="ml-auto flex gap-2">
          {dirty ? (
            <Button size="sm" onClick={() => setDraft({ ...data })}>
              Hủy thay đổi
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="primary"
            loading={save.isPending}
            disabled={!dirty}
            onClick={() =>
              save.mutate(draft, {
                onSuccess: () => toast("Đã lưu cấu hình dịch chung."),
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              })
            }
          >
            Lưu
          </Button>
        </div>
      </div>

      <Panel className="mb-4 overflow-hidden">
        <PanelHeader title="Văn phong & ngôn ngữ" />
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 p-4 md:grid-cols-2 lg:grid-cols-3">
          <Field label="Thể loại" hint="Quyết định preset xưng hô & thuật ngữ">
            <Select value={draft.genre} onChange={(e) => set("genre", e.target.value)}>
              {(draft.genres?.length ? draft.genres : [{ value: "auto", label: "auto" }]).map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Ngôn ngữ nguồn" hint="Để trống cho Trung văn">
            <Select value={draft.source_language} onChange={(e) => set("source_language", e.target.value)}>
              <option value="">Trung (mặc định)</option>
              <option value="en">Anh</option>
              <option value="vi">Việt (không cần dịch)</option>
            </Select>
          </Field>
          <Field label="Ngôn ngữ đích" hint="Mặc định: vi">
            <Input value={draft.target_language} onChange={(e) => set("target_language", e.target.value)} />
          </Field>
          <Field label="Tông giọng">
            <Input value={draft.tone} onChange={(e) => set("tone", e.target.value)} />
          </Field>
          <Field label="Chính sách xưng hô">
            <Select value={draft.pronoun_policy} onChange={(e) => set("pronoun_policy", e.target.value)}>
              <option value="contextual">Theo ngữ cảnh</option>
              <option value="formal">Trang trọng</option>
              <option value="modern_casual">Hiện đại, đời thường</option>
            </Select>
          </Field>
          <Field label="Xử lý tiêu đề">
            <Select value={draft.title_mode} onChange={(e) => set("title_mode", e.target.value)}>
              <option value="creative">Sáng tạo</option>
              <option value="literal">Sát nghĩa</option>
            </Select>
          </Field>
          <Field label="Mức Hán Việt">
            <Select value={draft.han_viet_level} onChange={(e) => set("han_viet_level", e.target.value)}>
              <option value="light">Nhẹ</option>
              <option value="balanced">Cân bằng</option>
              <option value="heavy">Đậm</option>
            </Select>
          </Field>
          <div className="flex items-end pb-1">
            <label className="flex items-center gap-2 py-1 text-[13px]">
              <Checkbox
                checked={draft.keep_paragraphs}
                onChange={(e) => set("keep_paragraphs", e.target.checked)}
              />
              Giữ nguyên cách chia đoạn
            </label>
          </div>
        </div>
      </Panel>

      <Panel className="mb-4 overflow-hidden">
        <PanelHeader
          title="Prompt dịch"
          hint="Placeholder ({text}, {glossary}, {tone}…) được pipeline điền khi dịch"
          actions={
            <Button size="sm" onClick={() => setPromptFullscreen(true)}>
              Xem toàn màn hình
            </Button>
          }
        />
        <div className="grid gap-x-4 gap-y-3 p-4 lg:grid-cols-2">
          <Field label="Prompt dịch chương">
            <Textarea
              rows={8}
              spellCheck={false}
              value={draft.prompt_template}
              onChange={(e) => set("prompt_template", e.target.value)}
            />
          </Field>
          <Field label="Prompt dịch tiêu đề">
            <Textarea
              rows={8}
              spellCheck={false}
              value={draft.title_prompt_template}
              onChange={(e) => set("title_prompt_template", e.target.value)}
            />
          </Field>
        </div>
      </Panel>

      <Panel className="mb-4 overflow-hidden">
        <PanelHeader
          title="Giới hạn & hiệu năng"
          hint="Số ký tự/token tối đa mỗi lần gọi, chia chunk, retry và số luồng"
        />
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 p-4 md:grid-cols-2 lg:grid-cols-3">
          <Field label="Giới hạn ký tự prompt" hint="Mỗi request cắt tại đây (mặc định 20000)">
            <Input
              type="number"
              min={0}
              value={draft.prompt_max_chars}
              onChange={(e) => set("prompt_max_chars", Number(e.target.value))}
            />
          </Field>
          <Field label="Cắt chunk tại (ký tự)" hint="0 = không cắt">
            <Input
              type="number"
              min={0}
              value={draft.chunk_max_chars}
              onChange={(e) => set("chunk_max_chars", Number(e.target.value))}
            />
          </Field>
          <Field label="Số đoạn chồng lấn giữa chunk">
            <Input
              type="number"
              min={0}
              value={draft.chunk_overlap_paragraphs}
              onChange={(e) => set("chunk_overlap_paragraphs", Number(e.target.value))}
            />
          </Field>
          <Field label="Số chương / lần gọi API">
            <Input
              type="number"
              min={1}
              value={draft.batch_size}
              onChange={(e) => set("batch_size", Number(e.target.value))}
            />
          </Field>
          <Field label="Delay giữa các chương (giây)">
            <Input
              type="number"
              step={0.1}
              min={0}
              value={draft.delay_seconds}
              onChange={(e) => set("delay_seconds", Number(e.target.value))}
            />
          </Field>
          <Field label="Số luồng dịch song song">
            <Input
              type="number"
              min={1}
              value={draft.max_workers}
              onChange={(e) => set("max_workers", Number(e.target.value))}
            />
          </Field>
          <Field label="Số lần thử lại">
            <Input
              type="number"
              min={1}
              value={draft.retry_attempts}
              onChange={(e) => set("retry_attempts", Number(e.target.value))}
            />
          </Field>
          <Field label="Delay thử lại (giây)">
            <Input
              type="number"
              step={0.1}
              min={0}
              value={draft.retry_delay_seconds}
              onChange={(e) => set("retry_delay_seconds", Number(e.target.value))}
            />
          </Field>
        </div>
      </Panel>

      <Panel className="overflow-hidden">
        <PanelHeader title="Glossary & dọn chữ Hán" />
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 p-4 md:grid-cols-2 lg:grid-cols-3">
          <label className="flex items-center gap-2 py-1 text-[13px]">
            <Checkbox checked={draft.auto_glossary} onChange={(e) => set("auto_glossary", e.target.checked)} />
            Tự cập nhật glossary sau khi dịch API
          </label>
          <label className="flex items-center gap-2 py-1 text-[13px]">
            <Checkbox checked={draft.use_idioms} onChange={(e) => set("use_idioms", e.target.checked)} />
            Dùng từ điển thành ngữ chung
          </label>
          <label className="flex items-center gap-2 py-1 text-[13px]">
            <Checkbox
              checked={draft.ai_glossary_analysis}
              onChange={(e) => set("ai_glossary_analysis", e.target.checked)}
            />
            Cho AI phân tích glossary từng chương
          </label>
          <label className="flex items-center gap-2 py-1 text-[13px]">
            <Checkbox
              checked={draft.auto_cleanup_han}
              onChange={(e) => set("auto_cleanup_han", e.target.checked)}
            />
            Tự dọn Hán tự sót lại
          </label>
          <Field label="Engine dọn chữ Hán">
            <Select value={draft.cleanup_han_engine} onChange={(e) => set("cleanup_han_engine", e.target.value)}>
              <option value="local_mt">Local MT offline</option>
              <option value="openai">AI biên tập</option>
            </Select>
          </Field>
          <Field label="Giới hạn ký tự dọn Hán" hint="Mặc định: 18000">
            <Input
              type="number"
              min={0}
              value={draft.cleanup_han_max_chars}
              onChange={(e) => set("cleanup_han_max_chars", Number(e.target.value))}
            />
          </Field>
          <Field label="Số lần thử lại dọn Hán">
            <Input
              type="number"
              min={0}
              value={draft.cleanup_han_retries}
              onChange={(e) => set("cleanup_han_retries", Number(e.target.value))}
            />
          </Field>
        </div>
      </Panel>

      <p className="mt-3 text-xs opacity-50">
        Lưu vào defaults.translate trong DB — các truyện đã có cấu hình riêng KHÔNG bị ảnh hưởng.
      </p>

      <Modal
        open={promptFullscreen}
        onClose={() => setPromptFullscreen(false)}
        title="Prompt dịch (toàn màn hình)"
        fullscreen
        footer={<Button onClick={() => setPromptFullscreen(false)}>Đóng</Button>}
      >
        <div className="grid min-h-full gap-4 lg:grid-cols-2">
          <Field label="Prompt dịch chương" hint="Các placeholder trong ngoặc nhọn được pipeline điền khi dịch.">
            <Textarea
              rows={20}
              spellCheck={false}
              className="min-h-[55vh] resize-y font-mono text-xs leading-5 lg:min-h-full"
              value={draft.prompt_template}
              onChange={(e) => set("prompt_template", e.target.value)}
            />
          </Field>
          <Field label="Prompt dịch tiêu đề" hint="Dùng khi dịch tên truyện và tiêu đề chương.">
            <Textarea
              rows={20}
              spellCheck={false}
              className="min-h-[55vh] resize-y font-mono text-xs leading-5 lg:min-h-full"
              value={draft.title_prompt_template}
              onChange={(e) => set("title_prompt_template", e.target.value)}
            />
          </Field>
        </div>
      </Modal>
    </Page>
  );
}
