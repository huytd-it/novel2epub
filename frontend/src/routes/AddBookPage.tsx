import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Page } from "@/app/Shell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import {
  useCreateEbook,
  useCreateEbooksBulk,
  usePreviewEbook,
  usePreviewEbooksBulk,
  useTranslateMetadata,
  type BulkCreateItem,
  type BulkEbookResult,
  type BulkPreviewResult,
  type EbookCreateResult,
  type EbookPreview,
} from "@/lib/books";
import { useSources } from "@/lib/sources";

const MAX_BULK_URLS = 20;
const MODES = ["", "fetcher", "stealthy", "dynamic"];

function FetchToc({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <Checkbox checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5" />
      <span>
        <span className="font-medium">Lấy danh mục ngay</span>
        <span className="mt-0.5 block text-xs opacity-60">Tạo thêm job fetch-toc sau khi lưu truyện.</span>
      </span>
    </label>
  );
}

function SingleResult({ result, reset }: { result: EbookCreateResult; reset: () => void }) {
  return (
    <Panel className="border-success/40 bg-success/5 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Badge tone="celadon">Đã tạo</Badge>
          <h2 className="mt-2 font-display text-lg font-semibold">{result.name || result.slug}</h2>
          <p className="text-xs opacity-60">{result.slug}{result.toc_job ? " · Đã xếp job lấy mục lục" : ""}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="btn btn-primary btn-sm" to={`/ebooks/${result.slug}`}>Mở truyện</Link>
          <Button onClick={reset}>Thêm tiếp</Button>
          <Link className="btn btn-sm" to="/">Về thư viện</Link>
        </div>
      </div>
    </Panel>
  );
}

function TranslateMetaButton({
  values,
  onTranslated,
  disabled,
}: {
  values: { name: string; author: string; description: string };
  onTranslated: (patch: { name: string; author: string; description: string }) => void;
  disabled?: boolean;
}) {
  const mutation = useTranslateMetadata();
  const toast = useToast();
  const translate = async () => {
    try {
      const result = await mutation.mutateAsync({
        title: values.name,
        author: values.author,
        description: values.description,
        engine: "localmt",
      });
      onTranslated({
        name: result.title || values.name,
        author: result.author || values.author,
        description: result.description || values.description,
      });
      if (Object.keys(result.errors ?? {}).length) {
        toast("Dịch có 1 số field lỗi, giữ nguyên bản gốc. Chi tiết trong kết quả hợp đồng.", "info");
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), "error");
    }
  };
  return (
    <Button size="sm" variant="neutral" loading={mutation.isPending} disabled={disabled} onClick={translate}>
      Dịch meta bằng Local MT
    </Button>
  );
}

export function AddBookPage() {
  const [tab, setTab] = useState<"single" | "bulk">("single");
  return (
    <Page title="Thêm truyện" hint="Tạo từ một URL mục lục hoặc nhập tối đa 20 URL cùng lúc">
      <div role="tablist" className="tabs tabs-box mb-4 w-fit" aria-label="Kiểu nhập truyện">
        <button role="tab" className={`tab ${tab === "single" ? "tab-active" : ""}`} onClick={() => setTab("single")}>Nhập 1 link</button>
        <button role="tab" className={`tab ${tab === "bulk" ? "tab-active" : ""}`} onClick={() => setTab("bulk")}>Nhập hàng loạt</button>
      </div>
      {tab === "single" ? <SingleForm /> : <BulkForm />}
    </Page>
  );
}

function SingleForm() {
  const sources = useSources();
  const previewMutation = usePreviewEbook();
  const createMutation = useCreateEbook();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [source, setSource] = useState("");
  const [mode, setMode] = useState("");
  const [fetchToc, setFetchToc] = useState(false);
  const [preview, setPreview] = useState<EbookPreview | null>(null);
  const [result, setResult] = useState<EbookCreateResult | null>(null);

  const showError = (error: unknown) => toast(error instanceof Error ? error.message : String(error), "error");
  const runPreview = async () => {
    try {
      setPreview(await previewMutation.mutateAsync({ toc_url: url, source, scrapling_mode: mode }));
    } catch (error) { showError(error); }
  };
  const create = async (withPreview: boolean) => {
    try {
      const metadata = withPreview && preview ? preview : null;
      setResult(await createMutation.mutateAsync({
        toc_url: url, source, scrapling_mode: mode, fetch_toc: fetchToc,
        ...(metadata ? metadata : {}),
      }));
    } catch (error) { showError(error); }
  };
  const reset = () => { setUrl(""); setPreview(null); setResult(null); };

  if (result) return <SingleResult result={result} reset={reset} />;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
      <Panel>
        <PanelHeader title="Địa chỉ nguồn" hint="Xem trước để duyệt metadata, hoặc tạo thẳng để backend tự đọc." />
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          <Field label="URL mục lục" className="sm:col-span-2"><Input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." /></Field>
          <Field label="Nguồn" hint={source ? "Preset này được ép dùng dù domain không khớp." : "Tự nhận diện theo domain URL."}>
            <Select value={source} onChange={(e) => setSource(e.target.value)}><option value="">Tự động</option>{sources.data?.presets.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</Select>
          </Field>
          <Field label="Chế độ Scrapling"><Select value={mode} onChange={(e) => setMode(e.target.value)}>{MODES.map((item) => <option key={item} value={item}>{item || "Theo nguồn"}</option>)}</Select></Field>
          <div className="sm:col-span-2"><FetchToc checked={fetchToc} onChange={setFetchToc} /></div>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button variant="primary" loading={previewMutation.isPending} disabled={!url.trim()} onClick={runPreview}>Xem trước</Button>
            <Button loading={createMutation.isPending} disabled={!url.trim()} onClick={() => create(false)}>Tạo thẳng</Button>
            <Link className="btn btn-ghost btn-sm" to="/">Hủy</Link>
          </div>
        </div>
      </Panel>
      {preview ? (
        <Panel>
          <PanelHeader title="Duyệt trước khi tạo" hint={`${preview.chapter_count} chương · Nguồn ${preview.source || "không xác định"}`} />
          <div className="grid gap-3 p-4">
            {preview.cover_url ? <img src={preview.cover_url} alt="Bìa truyện" className="max-h-48 rounded-box object-cover" /> : null}
            <Field label="Slug"><Input value={preview.slug} onChange={(e) => setPreview({ ...preview, slug: e.target.value })} /></Field>
            <Field label="Tên truyện"><Input value={preview.name} onChange={(e) => setPreview({ ...preview, name: e.target.value })} /></Field>
            <Field label="Tác giả"><Input value={preview.author} onChange={(e) => setPreview({ ...preview, author: e.target.value })} /></Field>
            <Field label="URL bìa"><Input value={preview.cover_url} onChange={(e) => setPreview({ ...preview, cover_url: e.target.value })} /></Field>
            <Field label="Mô tả"><Textarea rows={5} value={preview.description} onChange={(e) => setPreview({ ...preview, description: e.target.value })} /></Field>
            <details className="rounded-box border border-base-300 p-3 text-xs"><summary className="cursor-pointer font-medium">Cấu hình crawl hiệu lực</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap opacity-70">{JSON.stringify(preview.crawl_preview, null, 2)}</pre></details>
            <Button variant="primary" loading={createMutation.isPending} onClick={() => create(true)}>Tạo truyện đã duyệt</Button>
            <TranslateMetaButton values={{ name: preview.name, author: preview.author, description: preview.description }} onTranslated={(patch) => setPreview({ ...preview, ...patch })} disabled={!preview.name.trim()} />
          </div>
        </Panel>
      ) : <Panel className="hidden place-items-center p-8 text-center text-sm opacity-55 xl:grid">Metadata và cấu hình crawl sẽ hiện ở đây sau khi xem trước.</Panel>}
    </div>
  );
}

function BulkPreviewItem({
  item,
  onUpdate,
  onTranslated,
}: {
  item: BulkPreviewResult;
  onUpdate: (patch: Partial<BulkPreviewResult>) => void;
  onTranslated: (patch: { name: string; author: string; description: string }) => void;
}) {
  if (item.status === "failed") {
    return (
      <div className="flex items-start justify-between gap-3 border-b border-base-300 p-3">
        <div className="min-w-0">
          <Badge tone="vermilion">Lỗi</Badge>
          <p className="mt-1 truncate text-xs" title={item.url}>{item.url}</p>
          {item.reason ? <p className="mt-1 text-xs text-error">{item.reason}</p> : null}
          <p className="mt-1 text-[11px] opacity-50">Bỏ qua hoặc kiểm tra lại URL — URL này sẽ được backend thử lại khi tạo.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-2 border-b border-base-300 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge tone="gold">{item.chapter_count ?? 0} chương</Badge>
          {item.source ? <span className="badge badge-ghost badge-xs">{item.source}</span> : null}
          <p className="truncate text-xs opacity-60" title={item.url}>{item.url}</p>
        </div>
        <TranslateMetaButton
          values={{ name: item.name ?? "", author: item.author ?? "", description: item.description ?? "" }}
          onTranslated={onTranslated}
          disabled={!item.name}
        />
      </div>
      <Field label="Tên truyện"><Input value={item.name ?? ""} onChange={(e) => onUpdate({ name: e.target.value })} /></Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Tác giả"><Input value={item.author ?? ""} onChange={(e) => onUpdate({ author: e.target.value })} /></Field>
        <Field label="Slug"><Input value={item.slug ?? ""} onChange={(e) => onUpdate({ slug: e.target.value })} /></Field>
      </div>
      <Field label="Mô tả"><Textarea rows={2} value={item.description ?? ""} onChange={(e) => onUpdate({ description: e.target.value })} /></Field>
    </div>
  );
}

function BulkForm() {
  const previewMutation = usePreviewEbooksBulk();
  const createMutation = useCreateEbooksBulk();
  const toast = useToast();
  const [text, setText] = useState("");
  const [fetchToc, setFetchToc] = useState(false);
  const [previews, setPreviews] = useState<BulkPreviewResult[] | null>(null);
  const [results, setResults] = useState<BulkEbookResult[]>([]);
  const urls = text.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
  const showResults = results.length > 0;

  const updatePreview = (index: number, patch: Partial<BulkPreviewResult>) => {
    setPreviews((current) => current?.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) ?? null);
  };
  const runPreview = async (event: FormEvent) => {
    event.preventDefault();
    try { setPreviews((await previewMutation.mutateAsync({ toc_urls: urls })).results); }
    catch (error) { toast(error instanceof Error ? error.message : String(error), "error"); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const items: BulkCreateItem[] = (previews ?? [])
      .filter((item) => item.status === "ok" && item.name?.trim())
      .map((item) => ({
        url: item.url,
        slug: item.slug,
        name: item.name,
        author: item.author,
        description: item.description,
        cover_url: item.cover_url,
        source: item.source,
        scrapling_mode: item.scrapling_mode,
      }));
    try {
      setResults((await createMutation.mutateAsync({ toc_urls: urls, items, fetch_toc: fetchToc })).results);
    }
    catch (error) { toast(error instanceof Error ? error.message : String(error), "error"); }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,.9fr)]">
      <Panel><form onSubmit={submit} className="grid gap-4 p-4">
        <Field label="URL mục lục" hint={`${urls.length}/${MAX_BULK_URLS} URL · Nguồn được tự nhận diện riêng cho từng dòng.`}><Textarea rows={12} value={text} onChange={(e) => { setText(e.target.value); setPreviews(null); setResults([]); }} placeholder={"https://.../truyen-a\nhttps://.../truyen-b"} /></Field>
        <FetchToc checked={fetchToc} onChange={setFetchToc} />
        {urls.length > MAX_BULK_URLS ? <p role="alert" className="text-sm text-error">Vượt quá giới hạn {MAX_BULK_URLS} URL.</p> : null}
        <div className="flex flex-wrap gap-2">
          <Button variant="neutral" loading={previewMutation.isPending} disabled={!urls.length || urls.length > MAX_BULK_URLS} onClick={runPreview}>Xem trước</Button>
          <Button type="submit" variant="primary" loading={createMutation.isPending} disabled={!urls.length || urls.length > MAX_BULK_URLS}>Tạo {urls.length || ""} truyện{previews ? " đã duyệt" : ""}</Button>
          <Link className="btn btn-ghost btn-sm" to="/">Về thư viện</Link>
        </div>
      </form></Panel>
      <Panel aria-live="polite"><PanelHeader title={showResults ? "Kết quả" : previews ? "Duyệt trước khi tạo" : "Preview"} hint={showResults ? `${results.filter((item) => item.status === "created").length} truyện đã tạo` : previews ? "Sửa metadata từng URL rồi bấm Tạo." : "Xem trước để duyệt/sửa metadata từng URL trước khi tạo hàng loạt."} />
        <div className="divide-y divide-base-300">
          {showResults ? results.map((item, index) => <div key={`${item.url}-${index}`} className="flex items-start justify-between gap-3 p-3"><div className="min-w-0"><Badge tone={item.status === "created" ? "celadon" : item.status === "failed" ? "vermilion" : "gold"}>{item.status === "created" ? "Đã tạo" : item.status === "failed" ? "Lỗi" : "Đã tồn tại"}</Badge><p className="mt-1 truncate text-xs" title={item.url}>{item.url}</p>{item.reason ? <p className="mt-1 text-xs text-error">{item.reason}</p> : null}</div>{item.slug ? <Link className="btn btn-xs" to={`/ebooks/${item.slug}`}>Mở</Link> : null}</div>)
            : previews ? previews.map((item, index) => <BulkPreviewItem key={`${item.url}-${index}`} item={item} onUpdate={(patch) => updatePreview(index, patch)} onTranslated={(patch) => updatePreview(index, patch)} />)
            : <p className="p-8 text-center text-sm opacity-55">Bấm Xem trước để duyệt metadata từng URL — mỗi URL xử lý độc lập.</p>}
        </div>
      </Panel>
    </div>
  );
}
