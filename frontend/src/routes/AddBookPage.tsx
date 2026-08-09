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
  type BulkEbookResult,
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
          </div>
        </Panel>
      ) : <Panel className="hidden place-items-center p-8 text-center text-sm opacity-55 xl:grid">Metadata và cấu hình crawl sẽ hiện ở đây sau khi xem trước.</Panel>}
    </div>
  );
}

function BulkForm() {
  const mutation = useCreateEbooksBulk();
  const toast = useToast();
  const [text, setText] = useState("");
  const [fetchToc, setFetchToc] = useState(false);
  const [results, setResults] = useState<BulkEbookResult[]>([]);
  const urls = text.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try { setResults((await mutation.mutateAsync({ toc_urls: urls, fetch_toc: fetchToc })).results); }
    catch (error) { toast(error instanceof Error ? error.message : String(error), "error"); }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(360px,.9fr)]">
      <Panel><form onSubmit={submit} className="grid gap-4 p-4">
        <Field label="URL mục lục" hint={`${urls.length}/${MAX_BULK_URLS} URL · Nguồn được tự nhận diện riêng cho từng dòng.`}><Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} placeholder={"https://.../truyen-a\nhttps://.../truyen-b"} /></Field>
        <FetchToc checked={fetchToc} onChange={setFetchToc} />
        {urls.length > MAX_BULK_URLS ? <p role="alert" className="text-sm text-error">Vượt quá giới hạn {MAX_BULK_URLS} URL.</p> : null}
        <div className="flex gap-2"><Button type="submit" variant="primary" loading={mutation.isPending} disabled={!urls.length || urls.length > MAX_BULK_URLS}>Tạo {urls.length || ""} truyện</Button><Link className="btn btn-ghost btn-sm" to="/">Về thư viện</Link></div>
      </form></Panel>
      <Panel aria-live="polite"><PanelHeader title="Kết quả" hint={results.length ? `${results.filter((item) => item.status === "created").length} truyện đã tạo` : "Mỗi URL được xử lý độc lập"} />
        <div className="divide-y divide-base-300">{results.length ? results.map((item, index) => <div key={`${item.url}-${index}`} className="flex items-start justify-between gap-3 p-3"><div className="min-w-0"><Badge tone={item.status === "created" ? "celadon" : item.status === "failed" ? "vermilion" : "gold"}>{item.status === "created" ? "Đã tạo" : item.status === "failed" ? "Lỗi" : "Đã tồn tại"}</Badge><p className="mt-1 truncate text-xs" title={item.url}>{item.url}</p>{item.reason ? <p className="mt-1 text-xs text-error">{item.reason}</p> : null}</div>{item.slug ? <Link className="btn btn-xs" to={`/ebooks/${item.slug}`}>Mở</Link> : null}</div>) : <p className="p-8 text-center text-sm opacity-55">Kết quả từng URL sẽ hiện tại đây.</p>}</div>
      </Panel>
    </div>
  );
}
