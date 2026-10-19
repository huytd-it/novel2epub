import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useSources } from "@/lib/sources";
import { ebookKey } from "@/lib/ebook";
import { settingsKey } from "@/lib/settings";
import { Button } from "@/components/ui/Button";
import { Checkbox, Input, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

interface Choice {
  position: number;
  action: "match" | "add" | "skip";
  old_index: number | null;
  new_index: number | null;
}
interface SwitchPreview {
  old_fingerprint: string;
  toc_fingerprint: string;
  old_chapters: { index: number; title: string; url: string }[];
  rows: (Choice & { title: string; url: string; ordinal: number | null; has_raw: boolean; ambiguous: boolean })[];
}

export function SourceSwitchDialog({ slug, open, onClose, currentUrl }: {
  slug: string; open: boolean; onClose: () => void; currentUrl: string;
}) {
  const toast = useToast();
  const client = useQueryClient();
  const { data: sources, error: sourcesError } = useSources();
  const [sourceName, setSourceName] = useState("");
  const [tocUrl, setTocUrl] = useState("");
  const [crawlMode, setCrawlMode] = useState<"fetcher" | "stealthy">("fetcher");
  const [headless, setHeadless] = useState(true);
  const [preview, setPreview] = useState<SwitchPreview | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setChoices([]);
      setError("");
      setSourceName("");
      setTocUrl("");
    }
  }, [open]);

  const invalidate = () => { setPreview(null); setChoices([]); setError(""); };
  const changeChoice = (position: number, value: string) => {
    setChoices((prev) => prev.map((choice) => choice.position !== position ? choice :
      value === "match"
        ? { ...choice, action: "match", new_index: null }
        : { ...choice, action: value as "add" | "skip", old_index: null,
            new_index: value === "add" ? choice.new_index : null }));
  };
  const run = async (confirm: boolean) => {
    setPending(true);
    setError("");
    try {
      if (confirm && preview) {
        const result = await api.post<{ matched: number; added: number }>(`/api/ui/ebooks/${slug}/source-switch/confirm`, {
          body: { source_name: sourceName, toc_url: tocUrl, crawl_mode: crawlMode, headless,
            old_fingerprint: preview.old_fingerprint,
            toc_fingerprint: preview.toc_fingerprint, choices },
        });
        await Promise.all([
          client.invalidateQueries({ queryKey: ebookKey(slug) }),
          client.invalidateQueries({ queryKey: ["chapters", slug] }),
          client.invalidateQueries({ queryKey: settingsKey(slug) }),
        ]);
        toast(`Đã chuyển nguồn: ghép ${result.matched} chương, thêm ${result.added} chương. Bản dịch cũ được giữ nguyên.`);
        onClose();
      } else {
        const result = await api.post<SwitchPreview>(`/api/ui/ebooks/${slug}/source-switch/preview`, {
          body: { source_name: sourceName, toc_url: tocUrl, crawl_mode: crawlMode, headless },
        });
        setPreview(result);
        setChoices(result.rows.map(({ position, action, old_index, new_index }) => ({ position, action, old_index, new_index })));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      if (confirm) { setPreview(null); setChoices([]); }
    } finally { setPending(false); }
  };
  const matched = choices.filter((c) => c.action === "match").length;
  const added = choices.filter((c) => c.action === "add").length;
  const skipped = choices.length - matched - added;
  const used = choices.filter((c) => c.action === "match").map((c) => c.old_index);
  const duplicate = used.some((id, index) => used.indexOf(id) !== index);
  const oldByIndex = new Map(preview?.old_chapters.map((ch) => [ch.index, ch]) ?? []);
  const invalidMatch = choices.some((c) => c.action === "match" && !oldByIndex.has(c.old_index ?? -1));
  const addIndexes = choices.filter((c) => c.action === "add" && c.new_index !== null).map((c) => c.new_index!);
  const invalidAdd = addIndexes.some((idx, position) => idx <= 0 || oldByIndex.has(idx) || addIndexes.indexOf(idx) !== position);

  return (
    <Modal open={open} onClose={() => !pending && onClose()} title="Chuyển nguồn truyện" wide footer={<>
      <Button disabled={pending} onClick={onClose}>Đóng</Button>
      {preview ? <Button variant="primary" loading={pending} disabled={duplicate || invalidMatch || invalidAdd || matched + added === 0}
        onClick={() => run(true)}>Xác nhận chuyển nguồn</Button> :
        <Button variant="primary" loading={pending} disabled={!sourceName || !tocUrl.trim()}
          onClick={() => run(false)}>Xem trước ghép chương</Button>}
    </>}>
      <div className="space-y-4 text-[13px]">
        <p className="text-base-content/70">Ghép chương của nguồn mới vào index đã có; cập nhật URL và tiêu đề gốc để lần lấy mục lục sau không tạo chương trùng. Bản gốc, bản dịch và tiêu đề đã dịch/chỉnh tay được giữ nguyên.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block min-w-0"><span className="mb-1 block font-medium">Nguồn mới (preset)</span>
            <Select className="w-full" value={sourceName} disabled={pending} onChange={(e) => {
              const next = sources?.presets.find((s) => s.name === e.target.value);
              setSourceName(e.target.value);
              setCrawlMode(next?.scrapling_mode === "stealthy" ? "stealthy" : "fetcher");
              setHeadless(next?.headless ?? true);
              invalidate();
            }}>
              <option value="">Chọn nguồn</option>
              {sources?.presets.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </Select>
          </label>
          <label className="block min-w-0"><span className="mb-1 block font-medium">URL mục lục mới</span>
            <Input className="w-full" type="url" value={tocUrl} disabled={pending}
              placeholder="https://..." onChange={(e) => { setTocUrl(e.target.value); invalidate(); }} />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <label className="flex items-center gap-2"><span className="font-medium">Chế độ Crawl</span>
            <Select value={crawlMode} disabled={pending} onChange={(e) => {
              setCrawlMode(e.target.value as "fetcher" | "stealthy"); invalidate();
            }}>
              <option value="fetcher">Fetcher — HTTP</option>
              <option value="stealthy">Stealthy — trình duyệt</option>
            </Select>
          </label>
          <label className="flex cursor-pointer items-center gap-2" title={crawlMode === "fetcher" ? "Fetcher không dùng trình duyệt nên không áp dụng Headless" : undefined}>
            <Checkbox checked={headless} disabled={pending || crawlMode === "fetcher"} onChange={(e) => {
              setHeadless(e.target.checked); invalidate();
            }} />
            Headless {crawlMode === "fetcher" ? "(không áp dụng với Fetcher)" : "(ẩn trình duyệt)"}
          </label>
        </div>
        <p className="break-all text-[11px] opacity-60">URL hiện tại: {currentUrl || "(chưa có)"}. Cấu hình crawl riêng của nguồn cũ sẽ được thay bằng preset mới.</p>
        {sourcesError && <p role="alert" className="text-error">Không tải được danh sách nguồn: {sourcesError instanceof Error ? sourcesError.message : String(sourcesError)}</p>}
        {error && <p role="alert" className="rounded-field bg-error/10 p-3 text-error">{error} Hãy kiểm tra lại rồi xem trước lần nữa.</p>}
        {preview && <>
          <p className="font-medium" aria-live="polite">{matched} ghép · {added} thêm · {skipped} bỏ qua / {choices.length} chương nguồn mới</p>
          {duplicate && <p role="alert" className="text-error">Một chương cũ được ghép nhiều lần. Hãy chọn mỗi chương cũ đúng một lần.</p>}
          {invalidMatch && <p role="alert" className="text-error">Nhập index của chương cũ có trong ebook trước khi xác nhận.</p>}
          {invalidAdd && <p role="alert" className="text-error">Index điền vào phải còn trống và không được chọn cho hai chương mới.</p>}
          <p className="text-xs opacity-70">Chỉ tự ghép khi số chương ở hai nguồn là duy nhất. Chương thiếu được thêm vào index trống nếu hai chương lân cận khớp; nếu không còn index trống, chương được thêm ở cuối và bạn có thể dùng “Sắp xếp lại” sau khi chuyển. Chương cũ không ghép vẫn giữ dữ liệu nhưng URL nguồn cũ có thể không crawl được sau khi chuyển.</p>
          <div className="max-h-[45vh] overflow-auto rounded-field border border-base-300">
            <table className="w-full min-w-[38rem] text-left text-xs">
              <thead className="sticky top-0 bg-base-200"><tr><th className="p-2">Nguồn mới</th><th className="p-2">Số</th><th className="p-2">Xử lý</th></tr></thead>
              <tbody>{preview.rows.map((row) => {
                const choice = choices.find((c) => c.position === row.position);
                return <tr key={row.position} className="border-t border-base-300">
                  <td className="max-w-0 p-2"><span className="block truncate" title={row.title}>{row.title || row.url}</span>
                    {row.ambiguous && <span className="text-warning">Số chương trùng — cần kiểm tra</span>}
                  </td>
                  <td data-numeric className="p-2">{row.ordinal ?? "—"}</td>
                  <td className="p-2"><div className="flex items-center gap-2"><Select className="min-w-0 flex-1" disabled={pending} aria-label={`Ghép chương nguồn mới ${row.position}`}
                    value={choice?.action ?? "skip"}
                    onChange={(e) => changeChoice(row.position, e.target.value)}>
                    <option value="skip">Bỏ qua</option><option value="add">Thêm chương mới</option>
                    <option value="match">Ghép vào chương cũ</option>
                  </Select>{choice?.action === "add" && <Input type="number" min={1} className="w-20 shrink-0" disabled={pending}
                    aria-label={`Index mới cho chương nguồn ${row.position}`}
                    value={choice.new_index ?? ""} placeholder="Cuối" title="Để trống để thêm ở cuối; điền index còn trống để lấp chương thiếu"
                    onChange={(e) => setChoices((prev) => prev.map((c) => c.position === row.position
                      ? { ...c, new_index: e.target.value === "" ? null : Number(e.target.value) } : c))} />}
                  {choice?.action === "match" && <Input type="number" min={1} className="w-20 shrink-0" disabled={pending}
                    aria-label={`Index chương cũ ghép với chương nguồn mới ${row.position}`}
                    value={choice.old_index ?? ""} placeholder="#" title={oldByIndex.get(choice.old_index ?? -1)?.title}
                    onChange={(e) => setChoices((prev) => prev.map((c) => c.position === row.position
                      ? { ...c, old_index: e.target.value === "" ? null : Number(e.target.value) } : c))} />}</div></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          <p className="text-xs opacity-70">Sau xác nhận, chọn Crawl để tải nội dung cho các chương còn thiếu bản gốc; chương đã có bản dịch không bị dịch lại.</p>
        </>}
      </div>
    </Modal>
  );
}
