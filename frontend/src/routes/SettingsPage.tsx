import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api, apiUrl, legacyUrl } from "@/lib/api";
import {
  useEbookSettings,
  useSaveSettings,
  type EbookSettings,
  type SettingsSection,
} from "@/lib/settings";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Combobox } from "@/components/ui/Combobox";
import { useToast } from "@/components/ui/Toast";
import { IconExternal, IconSettings } from "@/components/icons";

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
  switch (spec.kind) {
    case "checkbox":
      return (
        <label className="flex items-center gap-2 py-1 text-[13px]">
          <Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {spec.label}
          {spec.hint ? <span className="text-xs opacity-50">— {spec.hint}</span> : null}
        </label>
      );
    case "select":
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
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
          onChange={onChange}
        />
      );
    default:
      return (
        <Field label={spec.label} hint={spec.hint}>
          <Input
            type="text"
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
          />
        </Field>
      );
  }
}

const MODELS_CACHE_KEY = "n2e-models-cache";
const MODELS_UPDATED_EVENT = "n2e:models-updated";

function readModelsCache(): Record<string, string[]> {
  try {
    return JSON.parse(localStorage.getItem(MODELS_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeModelsCache(cache: Record<string, string[]>) {
  try {
    localStorage.setItem(MODELS_CACHE_KEY, JSON.stringify(cache));
  } catch {
    /* localStorage không có sẵn (private mode) — bỏ qua */
  }
}

/** Tải model từ {base_url}/models, merge vào cache theo base_url rồi báo cho mọi
 * Combobox model đang mở nạp lại. Trả {count, total, error?}. */
async function fetchAndMergeModels(
  baseUrl: string,
  apiKey: string,
): Promise<{ count: number; total: number; error?: string }> {
  const url = baseUrl.trim();
  if (!url) return { count: 0, total: 0, error: "Nhập base_url trước." };
  try {
    const resp = await fetch(
      apiUrl(`/settings/ai/models?base_url=${encodeURIComponent(url)}&api_key=${encodeURIComponent(apiKey.trim())}`),
    );
    const data = (await resp.json()) as { models?: string[]; error?: string };
    if (data.error) return { count: 0, total: 0, error: `Lỗi: ${data.error}` };
    const fresh = data.models ?? [];
    const cache = readModelsCache();
    const existing = Array.isArray(cache[url]) ? cache[url] : [];
    const merged = Array.from(new Set(existing.concat(fresh)));
    cache[url] = merged;
    writeModelsCache(cache);
    window.dispatchEvent(new CustomEvent(MODELS_UPDATED_EVENT, { detail: url }));
    return { count: fresh.length, total: merged.length };
  } catch (e) {
    return { count: 0, total: 0, error: `Lỗi: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/** Nạp models đã cache cho một base_url (rỗng nếu chưa có). */
function cachedModelsFor(baseUrl: string): string[] {
  const url = baseUrl.trim();
  if (!url) return [];
  const cached = readModelsCache()[url];
  return Array.isArray(cached) ? cached : [];
}

/** Ô base_url gắn liền nút "Tải models": click sẽ tải model về cache theo url. */
function BaseUrlField({
  label,
  hint,
  value,
  apiKey,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  apiKey: string;
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
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="join-item flex-1 min-w-0"
        />
        <Button
          size="sm"
          loading={loading}
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

/** Ô model: combobox đọc từ cache theo base_url, tự nạp lại khi có models mới. */
function ModelField({
  label,
  hint,
  value,
  baseUrl,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  baseUrl: string;
  onChange: (next: unknown) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    const url = baseUrl.trim();
    const cached = cachedModelsFor(url);
    setModels(cached);
    setStatus(cached.length ? `Đã nạp ${cached.length} model từ cache.` : "");
  }, [baseUrl]);

  useEffect(() => {
    const onUpdated = (e: Event) => {
      const url = (e as CustomEvent<string>).detail;
      if (url === baseUrl.trim()) {
        const cached = cachedModelsFor(url);
        setModels(cached);
        setStatus(cached.length ? `Đã nạp ${cached.length} model từ cache.` : "");
      }
    };
    window.addEventListener(MODELS_UPDATED_EVENT, onUpdated);
    return () => window.removeEventListener(MODELS_UPDATED_EVENT, onUpdated);
  }, [baseUrl]);

  return (
    <Field label={label} hint={hint}>
      <Combobox
        value={value}
        onChange={(v) => onChange(v)}
        options={models}
        placeholder="Chọn model..."
      />
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
}: {
  slug: string;
  section: S;
  title: string;
  hint?: string;
  fields: FieldSpec<EbookSettings[S]>[];
  server: EbookSettings[S];
  banner?: React.ReactNode;
  extraActions?: React.ReactNode;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState<EbookSettings[S]>(server);
  const save = useSaveSettings(slug, section);

  // Đồng bộ lại draft khi server trả dữ liệu mới (đổi truyện, hoặc sau khi lưu
  // thành công — server là nguồn sự thật, draft chỉ là bản nháp tạm thời).
  useEffect(() => setDraft(server), [server]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(server), [draft, server]);

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
  { key: "impersonate", label: "Impersonate (fingerprint trình duyệt)", kind: "text" },
  { key: "proxy", label: "Proxy", kind: "text" },
  { key: "headless", label: "Chạy headless", kind: "checkbox" },
  { key: "solve_cloudflare", label: "Giải Cloudflare challenge", kind: "checkbox" },
  { key: "network_idle", label: "Đợi mạng nhàn rỗi trước khi đọc trang", kind: "checkbox" },
  { key: "dns_over_https", label: "DNS-over-HTTPS", kind: "checkbox" },
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

const AI_FIELDS: FieldSpec<EbookSettings["ai"]>[] = [
  { key: "base_url", label: "Base URL", kind: "base_url" },
  { key: "model", label: "Model", kind: "model" },
  { key: "api_key", label: "API key", kind: "password" },
  { key: "timeout_seconds", label: "Timeout (giây)", kind: "number" },
  { key: "temperature", label: "Temperature", kind: "number", step: 0.1 },
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
  const test = useMutation({
    mutationFn: (vars: { base_url: string; api_key: string }) =>
      api.post<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string }>(
        `/ebooks/${slug}/settings/translate/test`,
        { form: { base_url: vars.base_url, api_key: vars.api_key, timeout_seconds: 15 } },
      ),
  });

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
    { key: "base_url", label: "Base URL dịch API", kind: "base_url", wide: true },
    { key: "model", label: "Model dịch API", kind: "model" },
    { key: "api_key", label: "API key dịch API", kind: "password" },
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
    { key: "timeout_seconds", label: "Timeout (giây)", kind: "number" },
    { key: "temperature", label: "Temperature", kind: "number", step: 0.1 },
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
      hint="Backend dịch OpenAI-compatible, văn phong, glossary và giới hạn prompt"
      fields={fields}
      server={server}
      extraActions={
        <Button
          size="sm"
          loading={test.isPending}
          onClick={() => test.mutate({ base_url: server.base_url, api_key: server.api_key })}
        >
          Thử kết nối
        </Button>
      }
      banner={
        test.data ? (
          <div className={clsx(
            "flex flex-wrap items-center gap-2 border-b border-base-300 px-4 py-2 text-[13px]",
            test.data.ok ? "bg-success/10" : "bg-error/10",
          )}>
            <Badge tone={test.data.ok ? "celadon" : "vermilion"}>
              {test.data.ok ? "Kết nối OK" : "Lỗi kết nối"}
            </Badge>
            <span className="opacity-70">
              {test.data.ok ? `${test.data.model_count} model · ${test.data.latency_ms}ms` : test.data.error}
            </span>
          </div>
        ) : null
      }
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

function AiEditingTab({ slug, server }: { slug: string; server: EbookSettings["ai"] }) {
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; latency_ms?: number; model_count?: number; error?: string }>(
      `/ebooks/${slug}/settings/translate/test`,
      { form: { base_url: server.base_url, api_key: server.api_key, timeout_seconds: 15 } },
    ),
  });

  return (
    <SectionForm
      slug={slug}
      section="ai"
      title="AI biên tập"
      hint="Backend riêng cho rewrite, sửa ghi chú, glossary, nhân vật và đánh giá bản dịch"
      fields={AI_FIELDS}
      server={server}
      extraActions={<Button size="sm" loading={test.isPending} onClick={() => test.mutate()}>Thử kết nối</Button>}
      banner={
        <div className={clsx(
          "flex flex-wrap items-center gap-2 border-b border-base-300 px-4 py-2 text-[13px]",
          test.data ? (test.data.ok ? "bg-success/10" : "bg-error/10") : "bg-base-200/50",
        )}>
          <Badge tone={test.data ? (test.data.ok ? "celadon" : "vermilion") : "neutral"}>
            {test.data ? (test.data.ok ? "Kết nối OK" : "Lỗi kết nối") : "Backend riêng"}
          </Badge>
          <span className="opacity-70">
            {test.data
              ? (test.data.ok ? `${test.data.model_count} model · ${test.data.latency_ms}ms` : test.data.error)
              : "Nếu chưa có override AI, backend sẽ kế thừa cấu hình OpenAI ở tab Dịch API."}
          </span>
        </div>
      }
    />
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

const TABS = [
  { key: "novel", label: "Truyện" },
  { key: "source", label: "Nguồn" },
  { key: "translate", label: "Dịch API" },
  { key: "localmt", label: "Local MT" },
  { key: "ai", label: "AI biên tập" },
  { key: "reader", label: "Reader" },
  { key: "output", label: "Đầu ra" },
] as const;

export function SettingsPage() {
  const { slug = "" } = useParams();
  const { data, isPending, error } = useEbookSettings(slug);
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("novel");

  if (isPending) {
    return (
      <Page title="Đang tải cài đặt">
        <div className="flex items-center justify-center gap-2 py-20 text-sm opacity-60">
          <Spinner /> Đang đọc cấu hình
        </div>
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
      <a
        href={legacyUrl(`/ebooks/${slug}/settings`)}
        className="ml-auto inline-flex items-center gap-1 text-[11px] opacity-60 hover:text-primary hover:opacity-100"
      >
        Lưu vào nguồn / Reset (giao diện cũ) <IconExternal size={11} />
      </a>
    </div>
  ) : null;

  return (
    <Page
      title="Cài đặt"
      hint={<>{slug} · lưu theo từng mục, không cần lưu tất cả cùng lúc</>}
      actions={
        <Button
          variant="ghost"
          icon={<IconSettings size={15} />}
          onClick={() => {
            window.location.href = legacyUrl(`/ebooks/${slug}/settings`);
          }}
        >
          Giao diện cài đặt cũ
        </Button>
      }
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
      {tab === "translate" ? <TranslateTab slug={slug} server={data.translate} meta={data.meta} /> : null}
      {tab === "localmt" ? <LocalMtTab slug={slug} server={data.translate} /> : null}
      {tab === "ai" ? <AiEditingTab slug={slug} server={data.ai} /> : null}
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
        Tải ảnh bìa từ máy, đồng bộ vào nguồn dùng chung và các thao tác nâng cao khác vẫn ở{" "}
        <a href={legacyUrl(`/ebooks/${slug}/settings`)} className="inline-flex items-center gap-1 hover:text-primary">
          giao diện cũ <IconExternal size={11} />
        </a>
        .
      </p>
    </Page>
  );
}
