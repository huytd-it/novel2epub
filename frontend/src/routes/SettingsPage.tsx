import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api } from "@/lib/api";
import {
  useEbookSettings,
  useGlobalAi,
  useSaveSettings,
  useEbookModelOverrides,
  useSaveEbookModelOverrides,
  type AiSettings,
  type EbookSettings,
  type OpdsSettings,
  type SettingsSection,
} from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { fetchAndMergeModels, ModelField } from "@/components/AiProviderFields";

/* ── Mô tả field dùng chung cho mọi tab ──────────────────────────────── */

type Kind = "text" | "password" | "textarea" | "number" | "checkbox" | "select" | "model" | "base_url";

interface FieldSpec<T> {
  key: keyof T & string;
  label: string;
  kind: Kind;
  hint?: string;
  options?: { value: string; label: string }[];
  wide?: boolean; // chiếm trọn hàng lưới — cho textarea dài, URL, prompt
  step?: number;
  // Vô hiệu hoá field dựa trên giá trị các field khác (ví dụ tuỳ chọn chỉ
  // có nghĩa khi scrapling_mode là stealthy/dynamic). Khi bị vô hiệu, UI ghi
  // chú thích rõ lý do để tránh cảm giác "bấm lưu mà không ăn".
  disabledWhen?: (values: Record<string, unknown>) => boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- infra dùng chung mọi tab, an toàn kiểu nằm ở nơi khai báo FIELDS
function FieldControl({
  spec,
  value,
  values,
  onChange,
}: {
  spec: FieldSpec<any>;
  value: unknown;
  values: Record<string, unknown>;
  onChange: (next: unknown) => void;
}) {
  const disabled = spec.disabledWhen ? spec.disabledWhen(values) : false;
  const disabledNote = disabled ? (
    <span className="text-xs opacity-50">— không áp dụng ở chế độ hiện tại</span>
  ) : null;
  switch (spec.kind) {
    case "checkbox":
      return (
        <label className={clsx("flex items-center gap-2 py-1 text-[13px]", disabled && "opacity-50")}>
          <Checkbox checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          {spec.label}
          {spec.hint ? <span className="text-xs opacity-50">— {spec.hint}</span> : null}
          {disabled ? disabledNote : null}
        </label>
      );
    case "select":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Select value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
            {(spec.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
      );
    case "textarea":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Textarea
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            rows={spec.wide ? 8 : 3}
            spellCheck={false}
          />
        </Field>
      );
    case "number":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="number"
            step={spec.step ?? 1}
            value={String(value ?? 0)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
          />
        </Field>
      );
    case "password":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="password"
            autoComplete="off"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          />
        </Field>
      );
    case "model":
      return (
        <ModelField
          label={spec.label}
          hint={spec.hint}
          value={String(value ?? "")}
          baseUrl={String(values.base_url ?? "")}
          disabled={disabled}
          onChange={onChange}
        />
      );
    case "base_url":
      return (
        <BaseUrlField
          label={spec.label}
          hint={spec.hint}
          value={String(value ?? "")}
          apiKey={String(values.api_key ?? "")}
          disabled={disabled}
          onChange={onChange}
        />
      );
    default:
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
          />
        </Field>
      );
  }
}

/** Ô base_url gắn liền nút "Tải models": click sẽ tải model về cache theo url. */
function BaseUrlField({
  label,
  hint,
  value,
  apiKey,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  apiKey: string;
  disabled?: boolean;
  onChange: (next: unknown) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");

  const load = async () => {
    setLoading(true);
    setStatus("Đang tải...");
    const r = await fetchAndMergeModels(value, apiKey);
    setStatus(r.error ?? `Đã tải ${r.count} model (cache ${r.total}).`);
    setLoading(false);
  };

  return (
    <Field label={label} hint={hint}>
      <div className="join w-full">
        <Input
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="join-item flex-1 min-w-0"
        />
        <Button
          size="sm"
          loading={loading}
          disabled={disabled}
          onClick={load}
          className="join-item shrink-0"
          title="Lấy danh sách model từ {base_url}/models và tự lưu cache theo url"
        >
          Tải models
        </Button>
      </div>
      {status ? <span className="block text-xs italic opacity-60">{status}</span> : null}
    </Field>
  );
}

function SectionForm<S extends SettingsSection>({
  slug,
  section,
  title,
  hint,
  fields,
  server,
  banner,
  extraActions,
  renderExtraActions,
}: {
  slug: string;
  section: S;
  title: string;
  hint?: string;
  fields: FieldSpec<EbookSettings[S]>[];
  server: EbookSettings[S];
  banner?: React.ReactNode;
  extraActions?: React.ReactNode;
  renderExtraActions?: (draft: EbookSettings[S], setDraft: React.Dispatch<React.SetStateAction<EbookSettings[S]>>) => React.ReactNode;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState<EbookSettings[S]>(server);
  const save = useSaveSettings(slug, section);

  // Đồng bộ lại draft khi server trả dữ liệu mới (đổi truyện, hoặc sau khi lưu
  // thành công — server là nguồn sự thật, draft chỉ là bản nháp tạm thời).
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(server), [draft, server]);

  // Chỉ đồng bộ lại draft từ server khi CHƯA có thay đổi chưa lưu. Nếu đang
  // sửa (dirty), bỏ qua: react-query có thể refetch (focus cửa sổ / interval)
  // trả về `server` tham chiếu MỚI, và hiệu ứng này chạy sẽ GHI ĐÈ toggle của
  // người dùng trước khi họ kịp bấm Lưu — triệu chứng "checkbox không lưu".
  useEffect(() => {
    if (!dirty) setDraft(server);
  }, [server, dirty]);

  const set = (key: string, value: unknown) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const onSave = () => {
    save.mutate(draft, {
      onSuccess: () => toast(`Đã lưu ${title.toLowerCase()}.`),
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title={title}
        hint={hint}
        actions={
          <>
            {extraActions}
            {renderExtraActions?.(draft, setDraft)}
            {dirty ? (
              <Button size="sm" onClick={() => setDraft(server)}>
                Hủy thay đổi
              </Button>
            ) : null}
            <Button size="sm" variant="primary" loading={save.isPending} disabled={!dirty} onClick={onSave}>
              Lưu
            </Button>
          </>
        }
      />
      {banner}
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 p-4 md:grid-cols-2 lg:grid-cols-3">
        {fields.map((spec) => (
          <div key={spec.key} className={clsx(spec.wide && "md:col-span-2 lg:col-span-3")}>
            <FieldControl
              spec={spec}
              value={draft[spec.key]}
              values={draft as unknown as Record<string, unknown>}
              onChange={(v) => set(spec.key, v)}
            />
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ── Đặc tả field theo từng tab ──────────────────────────────────────── */

const NOVEL_FIELDS: FieldSpec<EbookSettings["novel"]>[] = [
  { key: "title", label: "Tiêu đề", kind: "text" },
  { key: "author", label: "Tác giả", kind: "text" },
  { key: "language", label: "Ngôn ngữ", kind: "text" },
  { key: "publisher", label: "Nhà xuất bản", kind: "text" },
  { key: "pubdate", label: "Ngày xuất bản", kind: "text", hint: "YYYY-MM-DD" },
  { key: "series", label: "Series", kind: "text" },
  { key: "series_index", label: "Thứ tự trong series", kind: "text" },
  { key: "identifier", label: "Identifier", kind: "text", hint: "Để trống để giữ giá trị tự sinh hiện có" },
  { key: "cover_url", label: "URL ảnh bìa", kind: "text", hint: "Lưu là tải về ngay; để trống để gỡ ảnh", wide: true },
  { key: "description", label: "Mô tả", kind: "textarea", wide: true },
  { key: "subjects", label: "Chủ đề", kind: "textarea", hint: "1 chủ đề / dòng", wide: true },
];

const SOURCE_FIELDS: FieldSpec<EbookSettings["source"]>[] = [
  { key: "toc_url", label: "URL mục lục", kind: "text", wide: true },
  { key: "content_selector", label: "CSS selector nội dung", kind: "text" },
  { key: "chapter_link_pattern", label: "Regex link chương", kind: "text" },
  {
    key: "scrapling_mode",
    label: "Chế độ crawl",
    kind: "select",
    options: [
      { value: "fetcher", label: "fetcher (nhanh nhất)" },
      { value: "stealthy", label: "stealthy" },
      { value: "dynamic", label: "dynamic (render JS)" },
    ],
  },
  { key: "max_chapters", label: "Giới hạn số chương", kind: "number", hint: "0 = không giới hạn" },
  { key: "delay_seconds", label: "Delay giữa các request (giây)", kind: "number", step: 0.1 },
  { key: "max_workers", label: "Số luồng crawl song song", kind: "number" },
  { key: "concurrency_cap", label: "Trần song song theo nguồn", kind: "number", hint: "0 = mặc định theo chế độ crawl" },
  { key: "impersonate", label: "Impersonate (fingerprint trình duyệt)", kind: "text" },
  { key: "proxy", label: "Proxy", kind: "text" },
  { key: "headless", label: "Chạy headless", kind: "checkbox", disabledWhen: (v) => v.scrapling_mode === "fetcher" },
  { key: "solve_cloudflare", label: "Giải Cloudflare challenge", kind: "checkbox", disabledWhen: (v) => v.scrapling_mode === "fetcher" },
  { key: "network_idle", label: "Đợi mạng nhàn rỗi trước khi đọc trang", kind: "checkbox", disabledWhen: (v) => v.scrapling_mode === "fetcher" },
  { key: "dns_over_https", label: "DNS-over-HTTPS", kind: "checkbox", disabledWhen: (v) => v.scrapling_mode === "fetcher" },
  { key: "next_page_selector", label: "Selector trang kế (nội dung chương)", kind: "text" },
  { key: "next_page_url_pattern", label: "Regex URL trang kế", kind: "text" },
  { key: "max_pages_per_chapter", label: "Số trang tối đa / chương", kind: "number" },
  { key: "toc_next_page_selector", label: "Selector trang kế (mục lục)", kind: "text" },
  { key: "toc_max_pages", label: "Số trang mục lục tối đa", kind: "number" },
  { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
  { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
  { key: "retry_backoff", label: "Hệ số backoff", kind: "number", step: 0.1 },
  { key: "retry_max_delay_seconds", label: "Delay thử lại tối đa (giây)", kind: "number" },
  { key: "retry_respect_retry_after", label: "Tôn trọng header Retry-After", kind: "checkbox" },
  { key: "strip_patterns", label: "Regex loại bỏ nội dung thừa", kind: "textarea", hint: "1 pattern / dòng", wide: true },
];

const READER_FIELDS: FieldSpec<EbookSettings["reader"]>[] = [
  { key: "url", label: "URL Reader", kind: "text", wide: true },
  { key: "service_key", label: "Service key", kind: "password", wide: true },
  { key: "reader_slug", label: "Slug trên Reader", kind: "text" },
  { key: "free_chapters", label: "Số chương đọc miễn phí", kind: "number" },
  { key: "batch_size", label: "Số chương / lần đẩy", kind: "number" },
  { key: "timeout_seconds", label: "Timeout (giây)", kind: "number" },
  { key: "push_anchors", label: "Đẩy kèm anchor điều hướng", kind: "checkbox" },
  { key: "published", label: "Công khai trên Reader", kind: "checkbox" },
];

const OUTPUT_FIELDS: FieldSpec<EbookSettings["output"]>[] = [
  { key: "data_dir", label: "Thư mục dữ liệu", kind: "text", wide: true },
  { key: "epub_path", label: "Đường dẫn EPUB", kind: "text", wide: true },
  { key: "crawl_max_workers", label: "Số luồng crawl (toàn hàng đợi)", kind: "number" },
  { key: "translate_max_workers", label: "Số luồng dịch (toàn hàng đợi)", kind: "number" },
];

/* ── Dịch API / Local MT / AI biên tập ─────────────────────────────── */

const LOCAL_MT_MODELS = [
  { value: "hachimimt-60", label: "HachimiMT-60" },
  { value: "hachimimt-30", label: "HachimiMT-30" },
  { value: "moxhimt-60", label: "MoxhiMT-60" },
  { value: "moxhimt-30", label: "MoxhiMT-30" },
  { value: "hirashiba-medium", label: "HirashibaMT-Medium" },
  { value: "hirashiba-tiny", label: "HirashibaMT-Tiny" },
];

const LOCAL_MT_KEYS = LOCAL_MT_MODELS.map((item) => ({
  value: item.label,
  label: item.label,
}));

function TranslateTab({ slug, server, meta }: { slug: string; server: EbookSettings["translate"]; meta: EbookSettings["meta"] }) {
  const toast = useToast();
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const fields: FieldSpec<EbookSettings["translate"]>[] = [
    {
      key: "type",
      label: "Backend dịch",
      kind: "select",
      options: [
        { value: "openai", label: "Dịch API OpenAI-compatible" },
        { value: "localmt", label: "Local MT làm backend mặc định" },
        { value: "none", label: "Không dịch" },
      ],
    },
    {
      key: "preset",
      label: "Preset prompt",
      kind: "select",
      options: [
        { value: "", label: "Không dùng preset" },
        { value: "go", label: "Go" },
        { value: "omniroute", label: "OmniRoute" },
      ],
    },
    {
      key: "source_language",
      label: "Ngôn ngữ nguồn",
      kind: "select",
      options: [
        { value: "", label: "Trung (mặc định)" },
        { value: "en", label: "Anh" },
        { value: "vi", label: "Việt (không cần dịch)" },
      ],
    },
    { key: "target_language", label: "Ngôn ngữ đích", kind: "text", hint: "Mặc định: vi" },
    {
      key: "genre",
      label: "Thể loại",
      kind: "select",
      options: meta.genres.length ? meta.genres : [{ value: "auto", label: "auto" }],
    },
    { key: "tone", label: "Tông giọng", kind: "text" },
    {
      key: "pronoun_policy",
      label: "Chính sách xưng hô",
      kind: "select",
      options: [
        { value: "contextual", label: "Theo ngữ cảnh" },
        { value: "formal", label: "Trang trọng" },
        { value: "modern_casual", label: "Hiện đại, đời thường" },
      ],
    },
    {
      key: "title_mode",
      label: "Xử lý tiêu đề",
      kind: "select",
      options: [
        { value: "creative", label: "Sáng tạo" },
        { value: "literal", label: "Sát nghĩa" },
      ],
    },
    {
      key: "han_viet_level",
      label: "Mức Hán Việt",
      kind: "select",
      options: [
        { value: "light", label: "Nhẹ" },
        { value: "balanced", label: "Cân bằng" },
        { value: "heavy", label: "Đậm" },
      ],
    },
    { key: "keep_paragraphs", label: "Giữ nguyên cách chia đoạn", kind: "checkbox" },
    { key: "delay_seconds", label: "Delay giữa các chương (giây)", kind: "number", step: 0.1 },
    { key: "max_workers", label: "Số luồng dịch song song", kind: "number" },
    { key: "batch_size", label: "Số chương / lần gọi API", kind: "number" },
    { key: "prompt_max_chars", label: "Giới hạn ký tự prompt", kind: "number", hint: "Mặc định hiệu lực: 20000" },
    { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
    { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
    { key: "chunk_max_chars", label: "Cắt chunk tại (ký tự)", kind: "number", hint: "0 = không cắt" },
    { key: "chunk_overlap_paragraphs", label: "Số đoạn chồng lấn giữa chunk", kind: "number" },
    { key: "auto_glossary", label: "Tự cập nhật glossary sau khi dịch API", kind: "checkbox" },
    { key: "use_idioms", label: "Dùng từ điển thành ngữ chung", kind: "checkbox" },
    { key: "ai_glossary_analysis", label: "Cho AI phân tích glossary từng chương", kind: "checkbox", hint: "Chậm hơn; chỉ bật khi cần học domain mới" },
    { key: "profile", label: "Profile dịch", kind: "text", hint: "Mặc định: traditional_cn_novel" },
    { key: "prompt_template", label: "Prompt dịch chương", kind: "textarea", wide: true },
    { key: "title_prompt_template", label: "Prompt dịch tiêu đề", kind: "textarea", wide: true },
  ];

  return (
    <SectionForm
      slug={slug}
      section="translate"
      title="Dịch API"
      hint="Engine, văn phong, glossary và giới hạn prompt; provider/model được quản lý ở mục “Provider AI cho truyện này” bên dưới và Dịch chung"
      fields={fields}
      server={server}
      renderExtraActions={(draft, setDraft) => (
        <>
          <Button size="sm" onClick={() => setPreviewOpen(true)}>
            Xem prompt toàn màn hình
          </Button>
          <Button
            size="sm"
            loading={loadingPrompts}
            onClick={async () => {
              setLoadingPrompts(true);
              try {
                const language = encodeURIComponent(String(draft.source_language ?? ""));
                const prompts = await api.get<Pick<EbookSettings["translate"], "prompt_template" | "title_prompt_template">>(
                  `/settings/translate/default-prompts?source_language=${language}`,
                );
                setDraft((current) => ({ ...current, ...prompts }));
                toast("Đã nạp lại prompt mặc định. Bấm Lưu để áp dụng.");
              } catch (error) {
                toast(error instanceof Error ? error.message : String(error), "error");
              } finally {
                setLoadingPrompts(false);
              }
            }}
          >
            Nạp lại prompt
          </Button>
          <Modal
            open={previewOpen}
            onClose={() => setPreviewOpen(false)}
            title="Xem và chỉnh sửa prompt dịch"
            fullscreen
            footer={<Button onClick={() => setPreviewOpen(false)}>Đóng</Button>}
          >
            <div className="grid min-h-full gap-4 lg:grid-cols-2">
              <Field label="Prompt dịch chương" hint="Các placeholder trong ngoặc nhọn được pipeline điền khi dịch.">
                <Textarea
                  value={String(draft.prompt_template ?? "")}
                  onChange={(event) => setDraft((current) => ({ ...current, prompt_template: event.target.value }))}
                  className="min-h-[55vh] resize-y font-mono text-xs leading-5 lg:min-h-full"
                  spellCheck={false}
                />
              </Field>
              <Field label="Prompt dịch tiêu đề" hint="Prompt dùng riêng khi dịch tên truyện và tiêu đề chương.">
                <Textarea
                  value={String(draft.title_prompt_template ?? "")}
                  onChange={(event) => setDraft((current) => ({ ...current, title_prompt_template: event.target.value }))}
                  className="min-h-[40vh] resize-y font-mono text-xs leading-5 lg:min-h-full"
                  spellCheck={false}
                />
              </Field>
            </div>
          </Modal>
        </>
      )}
    />
  );
}

function LocalMtTab({ slug, server }: { slug: string; server: EbookSettings["translate"] }) {
  const fields: FieldSpec<EbookSettings["translate"]>[] = [
    {
      key: "local_model",
      label: "Preset model",
      kind: "select",
      hint: "Chọn preset sẽ quyết định model thực tế bên dưới",
      options: [{ value: "", label: "Dùng model key thủ công" }, ...LOCAL_MT_MODELS],
    },
    {
      key: "hachimimt_model_key",
      label: "Model key",
      kind: "select",
      options: LOCAL_MT_KEYS,
    },
    {
      key: "hachimimt_backend",
      label: "Runtime",
      kind: "select",
      hint: "Runtime hiện hỗ trợ CTranslate2",
      options: [{ value: "ctranslate2", label: "CTranslate2" }],
    },
    { key: "hachimimt_beam_size", label: "Beam size", kind: "number" },
    {
      key: "hachimimt_chunk_mode",
      label: "Chia nội dung theo",
      kind: "select",
      options: [
        { value: "sentence", label: "Câu" },
        { value: "paragraph", label: "Đoạn" },
      ],
    },
    { key: "source_language", label: "Ngôn ngữ nguồn", kind: "text", hint: "Để trống cho Trung văn" },
    { key: "target_language", label: "Ngôn ngữ đích", kind: "text", hint: "Mặc định: vi" },
    { key: "delay_seconds", label: "Delay giữa các chương (giây)", kind: "number", step: 0.1 },
    { key: "max_workers", label: "Số chương chạy song song", kind: "number" },
    { key: "retry_attempts", label: "Số lần thử lại", kind: "number" },
    { key: "retry_delay_seconds", label: "Delay thử lại (giây)", kind: "number", step: 0.1 },
    { key: "auto_cleanup_han", label: "Tự dọn Hán tự sót lại", kind: "checkbox" },
    {
      key: "cleanup_han_engine",
      label: "Engine dọn Hán tự",
      kind: "select",
      options: [
        { value: "local_mt", label: "Local MT offline" },
        { value: "openai", label: "AI biên tập" },
      ],
    },
    { key: "cleanup_han_max_chars", label: "Giới hạn ký tự dọn Hán", kind: "number", hint: "Mặc định: 18000" },
    { key: "cleanup_han_retries", label: "Số lần thử lại dọn Hán", kind: "number" },
  ];

  return (
    <SectionForm
      slug={slug}
      section="translate"
      title="Local MT"
      hint="Dịch hoàn toàn offline; không gọi Base URL hoặc API key của AI"
      fields={fields}
      server={server}
      banner={
        <div className="flex flex-wrap items-center gap-2 border-b border-base-300 bg-success/10 px-4 py-2 text-[13px]">
          <Badge tone="celadon">Offline</Badge>
          <span className="opacity-70">Action “Local MT” luôn ép engine Local MT, bất kể backend mặc định ở tab Dịch API.</span>
        </div>
      }
    />
  );
}

function TranslateAiProviderPanel({ slug, ai }: { slug: string; ai: AiSettings }) {
  const toast = useToast();
  const { data: globalAi } = useGlobalAi();
  const saveProvider = useSaveSettings(slug, "ai");
  const modelQuery = useEbookModelOverrides(slug);
  const saveModels = useSaveEbookModelOverrides(slug);

  const [baseUrl, setBaseUrl] = useState(ai.base_url);
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState(ai.timeout_seconds);
  const [temperature, setTemperature] = useState(ai.temperature);
  const [translationModel, setTranslationModel] = useState("");
  const [assistantModel, setAssistantModel] = useState("");
  const [test, setTest] = useState<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string } | null>(null);
  const [modelsStatus, setModelsStatus] = useState("");

  useEffect(() => {
    setBaseUrl(ai.base_url);
    setTimeoutSeconds(ai.timeout_seconds);
    setTemperature(ai.temperature);
  }, [ai.base_url, ai.timeout_seconds, ai.temperature]);

  useEffect(() => {
    if (modelQuery.data) {
      setTranslationModel(modelQuery.data.translation_model);
      setAssistantModel(modelQuery.data.assistant_model);
    }
  }, [modelQuery.data]);

  const baseUrlForModel = baseUrl || globalAi?.base_url || "";

  const onTest = async () => {
    try {
      const r = await api.post<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string }>(
        "/settings/ai/test",
        { body: { base_url: baseUrlForModel, api_key: apiKey || globalAi?.api_key || "", timeout_seconds: 15 } },
      );
      setTest(r);
    } catch (e) {
      setTest({ ok: false, error: e instanceof Error ? e.message : String(e) });
    }
  };

  const onLoadModels = async () => {
    setModelsStatus("Đang tải danh sách model…");
    const result = await fetchAndMergeModels(baseUrlForModel, apiKey || globalAi?.api_key || "");
    setModelsStatus(result.error ?? `Đã tải ${result.count} model${result.total > result.count ? ` · ${result.total} trong cache` : ""}`);
  };

  const onLoadFromGlobal = () => {
    if (!globalAi) return;
    setBaseUrl(globalAi.base_url);
    setTimeoutSeconds(globalAi.timeout_seconds);
    setTemperature(globalAi.temperature);
    setTranslationModel(globalAi.translation_model);
    setAssistantModel(globalAi.assistant_model);
  };

  const onReset = async () => {
    try {
      await api.post(`/ebooks/${slug}/settings/ai/reset`);
      setBaseUrl(globalAi?.base_url ?? "");
      setTimeoutSeconds(globalAi?.timeout_seconds ?? 120000);
      setTemperature(globalAi?.temperature ?? 0.7);
      setApiKey("");
      setTranslationModel("");
      setAssistantModel("");
      toast("Đã reset AI riêng về mặc định chung (Dịch chung).");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const onSave = async () => {
    try {
      await saveProvider.mutateAsync(
        { base_url: baseUrl, api_key: apiKey, timeout_seconds: timeoutSeconds, temperature, api_key_configured: ai.api_key_configured },
        { onSuccess: () => toast("Đã lưu provider AI riêng cho truyện này.") },
      );
      await saveModels.mutateAsync(
        { translation_model: translationModel, assistant_model: assistantModel },
        { onSuccess: () => toast("Đã lưu model AI riêng cho truyện này.") },
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <Panel className="mt-4 overflow-hidden">
      <PanelHeader
        title="AI riêng cho truyện này (ghi đè Dịch chung)"
        hint="Mỗi truyện có thể dùng provider, API key, timeout, temperature và model riêng — ghi đè hoàn toàn config AI chung."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={onLoadModels}>Tải models</Button>
            <Button size="sm" onClick={onTest}>Thử kết nối</Button>
            <Button size="sm" variant="ghost" onClick={onLoadFromGlobal}>Nạp lại từ Dịch chung</Button>
            <Button size="sm" variant="ghost" onClick={onReset}>Reset về chung</Button>
            <Button size="sm" variant="primary" loading={saveProvider.isPending || saveModels.isPending} onClick={onSave}>Lưu AI riêng</Button>
          </div>
        }
      />
      <div className="border-b border-base-300 bg-base-200/50 px-4 py-3 text-[13px]">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={ai.api_key_configured ? "celadon" : "gold"}>
            {ai.api_key_configured ? "Đã có API key riêng" : "Chưa có API key riêng (kế thừa chung)"}
          </Badge>
          <span className="opacity-70">Để trống API key khi lưu sẽ giữ nguyên secret hiện tại của truyện này.</span>
        </div>
        {globalAi ? (
          <p className="mt-2 opacity-70">
            Dịch chung — Base URL: <code>{globalAi.base_url}</code> · Translation: <code>{globalAi.translation_model || "(trống)"}</code> · Assistant: <code>{globalAi.assistant_model || "(trống)"}</code> · Timeout: {globalAi.timeout_seconds}s · Temp: {globalAi.temperature}
          </p>
        ) : null}
        {test ? (
          <p className={clsx("mt-2", test.ok ? "text-success" : "text-error")} role="status">
            {test.ok ? `Kết nối OK · ${test.model_count} model · ${test.latency_ms}ms` : test.error}
          </p>
        ) : null}
        {modelsStatus ? <p className="mt-2 opacity-70" role="status">{modelsStatus}</p> : null}
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <div className="md:col-span-2">
          <Field label="Base URL" hint="OpenAI-compatible endpoint, ví dụ https://host/v1">
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} spellCheck={false} />
          </Field>
        </div>
        <Field label="API key" hint={ai.api_key_configured ? "Nhập giá trị mới để thay key hiện tại" : "Credential riêng cho truyện này; để trống giữ nguyên"}>
          <Input type="password" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>
        <Field label="Timeout (giây)">
          <Input type="number" min={1} value={timeoutSeconds} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} />
        </Field>
        <ModelField
          label="Model dịch chương"
          hint="Để trống = dùng model chung từ Dịch chung"
          value={translationModel}
          baseUrl={baseUrlForModel}
          onChange={(value) => setTranslationModel(String(value))}
        />
        <ModelField
          label="Model trợ lý"
          hint="Glossary, rewrite, cleanup, Reader và metadata AI. Để trống = dùng chung"
          value={assistantModel}
          baseUrl={baseUrlForModel}
          onChange={(value) => setAssistantModel(String(value))}
        />
        <Field label="Temperature" hint="0–2">
          <Input type="number" min={0} max={2} step={0.1} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
        </Field>
      </div>
    </Panel>
  );
}

function OpdsTab({ server }: { server: OpdsSettings }) {
  const toast = useToast();
  const [values, setValues] = useState(server);
  useEffect(() => setValues(server), [server]);
  const save = useMutation({
    mutationFn: () => api.post<{ saved: boolean; opds: OpdsSettings }>(
      "/api/ui/settings/opds",
      { body: values },
    ),
    onSuccess: (result) => {
      setValues(result.opds);
      toast("Đã lưu cấu hình OPDS.");
    },
    onError: (error) => toast(error instanceof Error ? error.message : String(error), "error"),
  });

  return (
    <Panel>
      <PanelHeader
        title="OPDS"
        hint="Catalog dùng cho Readest và các ứng dụng đọc sách tương thích OPDS"
        actions={<Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Lưu OPDS</Button>}
      />
      <div className="border-b border-base-300 bg-base-200/50 px-4 py-3 text-[13px]">
        <Badge tone={values.token_configured ? "celadon" : "gold"}>
          {values.token_configured ? "Đã có token" : "Chưa có token"}
        </Badge>
        <span className="ml-2 opacity-70">Catalog: <code>/opds</code>. Để trống token khi lưu sẽ giữ nguyên token hiện tại.</span>
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <Field label="Token truy cập" hint="Nhập giá trị mới chỉ khi muốn thay token hiện tại">
          <Input type="password" autoComplete="new-password" value={values.token} onChange={(event) => setValues((current) => ({ ...current, token: event.target.value }))} />
        </Field>
        <div className="flex items-end pb-1">
          <label className="flex items-center gap-2 text-[13px]">
            <Checkbox checked={values.auto_build} onChange={(event) => setValues((current) => ({ ...current, auto_build: event.target.checked }))} />
            Tự build lại EPUB khi mở catalog
          </label>
        </div>
        <div className="md:col-span-2">
          <Field label="CORS origins" hint="Mỗi origin một dòng, ví dụ https://readest.com">
            <Textarea rows={5} spellCheck={false} value={values.cors_origins} onChange={(event) => setValues((current) => ({ ...current, cors_origins: event.target.value }))} />
          </Field>
        </div>
      </div>
    </Panel>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

const TABS = [
  { key: "novel", label: "Truyện" },
  { key: "source", label: "Nguồn" },
  { key: "translate", label: "Dịch" },
  { key: "localmt", label: "Local MT" },
  { key: "opds", label: "OPDS" },
  { key: "reader", label: "Reader" },
  { key: "output", label: "Đầu ra" },
] as const;

export function SettingsPage() {
  const { slug = "" } = useParams();
  const { data, isPending, error } = useEbookSettings(slug);
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("translate");

  if (isPending) {
    return (
      <Page title="Đang tải cài đặt" loading loadingLabel="Đang đọc cấu hình">
        {null}
      </Page>
    );
  }

  if (error || !data) {
    return (
      <Page title="Không mở được cài đặt">
        <Panel>
          <EmptyState
            title="Không đọc được cấu hình truyện này"
            hint={error instanceof Error ? error.message : String(error)}
          />
        </Panel>
      </Page>
    );
  }

  const sourceBanner = data.meta.source_name ? (
    <div className="flex flex-wrap items-center gap-2 border-b border-base-300 bg-base-200/50 px-4 py-2 text-[13px]">
      <span className="opacity-70">
        Nguồn: <span className="font-medium">{data.meta.source_name}</span>
        {data.meta.source_detected ? " (tự nhận diện theo URL)" : ""}
      </span>
      {data.meta.overridden_fields.length > 0 ? (
        <Badge tone="gold">{data.meta.overridden_fields.length} trường đã ghi đè nguồn</Badge>
      ) : null}
    </div>
  ) : null;

  return (
    <Page
      title="Cài đặt"
      hint={<>{slug} · lưu theo từng mục, không cần lưu tất cả cùng lúc</>}
    >
      <div role="tablist" className="tabs tabs-border mb-4">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            className={clsx("tab", tab === t.key && "tab-active")}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "opds" ? <OpdsTab server={data.opds} /> : null}
      {tab === "novel" ? (
        <SectionForm
          slug={slug}
          section="novel"
          title="Truyện"
          hint="Metadata dùng khi build EPUB"
          fields={NOVEL_FIELDS}
          server={data.novel}
        />
      ) : null}
      {tab === "source" ? (
        <SectionForm
          slug={slug}
          section="source"
          title="Nguồn"
          hint="Cách crawl mục lục và nội dung chương"
          fields={SOURCE_FIELDS}
          server={data.source}
          banner={sourceBanner}
        />
      ) : null}
      {tab === "translate" ? (
        <>
          <TranslateTab slug={slug} server={data.translate} meta={data.meta} />
          <TranslateAiProviderPanel slug={slug} ai={data.ai} />
        </>
      ) : null}
      {tab === "localmt" ? <LocalMtTab slug={slug} server={data.translate} /> : null}
      {tab === "reader" ? (
        <SectionForm
          slug={slug}
          section="reader"
          title="Reader"
          hint="Đẩy bản dịch sang app đọc novel-reader"
          fields={READER_FIELDS}
          server={data.reader}
        />
      ) : null}
      {tab === "output" ? (
        <SectionForm
          slug={slug}
          section="output"
          title="Đầu ra"
          hint="Vị trí lưu dữ liệu và số luồng xử lý"
          fields={OUTPUT_FIELDS}
          server={data.output}
        />
      ) : null}

      <p className="mt-3 text-xs opacity-50">
        Đồng bộ vào nguồn dùng chung, tải ảnh bìa từ máy và reset override vẫn chưa có mặt
        trong giao diện mới — tạm thời chỉnh thẳng trong file cấu hình nếu cần.
      </p>
    </Page>
  );
}
