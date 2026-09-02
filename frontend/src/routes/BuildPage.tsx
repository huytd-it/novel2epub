import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api, apiUrl } from "@/lib/api";
import { bytes, num, percent } from "@/lib/format";
import { useEbook } from "@/lib/ebook";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Badge, Dot } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { IconCheck, IconDownload, IconPlay, IconSearch, IconSettings } from "@/components/icons";
import { queueKey } from "@/lib/queue";

interface BuildPreview {
  has_manifest: boolean;
  total: number;
  skipped: number;
  ready: number;
  blocked: number;
  can_build: boolean;
  metadata: { code: string; level: string; field?: string; message: string; hint?: string }[];
  stats: {
    total: number;
    skipped: number;
    ready: number;
    blocked: number;
    will_include: number;
    will_exclude: number;
    word_count: number;
    char_count: number;
    avg_words: number;
    han_total: number;
    branches: Record<string, { count: number; label: string }>;
    chapters_with_issues: number;
  };
  validation: {
    summary: { error: number; warning: number; info: number; total_issues: number };
    groups: { code: string; level: string; count: number; message: string; examples: { index: number; title: string }[] }[];
    chapters: { index: number; title: string; skipped: boolean; issues: { code: string; level: string; message: string; hint?: string }[]; word_count: number; char_count: number; han_count: number }[];
  };
  preview: {
    chapters: { index: number; title: string; word_count: number; char_count: number; branch: string; snippet: string; issues: unknown[] }[];
    total_preview: number;
    total_will_include: number;
    cover: { has_cover: boolean; cover_file: string; cover_url: string };
    epub: { exists: boolean; path: string; size: number; stale: boolean; build: { status: string; error: string; finished_at: string; started_at: string } };
    will_include: number;
    will_exclude: number;
    toc_url: string;
    language: string;
    title: string;
    author: string;
    publisher: string;
  };
  blockers: { index: number; title: string; reason: string }[];
}

function levelTone(level: string) {
  if (level === "error") return "vermilion" as const;
  if (level === "warning") return "gold" as const;
  return "neutral" as const;
}

function StatCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={clsx("rounded-box border bg-base-100 px-3 py-3", tone === "error" ? "border-error/30" : tone === "warning" ? "border-warning/30" : "border-base-300")}>
      <p className="text-[10px] tracking-[0.1em] uppercase opacity-50">{label}</p>
      <p data-numeric className="mt-1 text-xl font-semibold leading-none">{value}</p>
      {hint ? <p className="mt-1 text-[11px] opacity-60">{hint}</p> : null}
    </div>
  );
}

export function BuildPage() {
  const { slug = "" } = useParams();
  const toast = useToast();
  const client = useQueryClient();
  const [force, setForce] = useState(false);
  const [showAllGroups, setShowAllGroups] = useState(false);

  const ebook = useEbook(slug);
  const previewQ = useQuery({
    queryKey: ["build-preview", slug],
    queryFn: () => api.get<BuildPreview>(`/api/ui/ebooks/${slug}/build/preview`),
    enabled: Boolean(slug),
  });

  const buildMut = useMutation({
    mutationFn: () => api.post<{ ok: boolean; job_id: string }>(`/api/ui/ebooks/${slug}/build/confirm`, { body: { force } }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queueKey });
      client.invalidateQueries({ queryKey: ["build-preview", slug] });
      client.invalidateQueries({ queryKey: ["ebook", slug] });
      toast("Đã xếp job Build EPUB vào hàng đợi.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const data = previewQ.data;
  const loading = previewQ.isLoading;

  if (loading) {
    return (
      <Page title="Build sách" hint="Đang kiểm tra dữ liệu…" loading loadingLabel="Đang tải preview build">
        <div />
      </Page>
    );
  }

  if (previewQ.isError) {
    return (
      <Page title="Build sách" hint={slug}>
        <EmptyState
          title="Không tải được preview build"
          hint={previewQ.error instanceof Error ? previewQ.error.message : String(previewQ.error)}
          action={<Button onClick={() => previewQ.refetch()}>Thử lại</Button>}
        />
      </Page>
    );
  }

  if (!data) return null;
  if (!data.has_manifest) {
    return (
      <Page title="Build sách" hint={ebook.data?.title || slug} actions={<Link to={`/ebooks/${slug}`} className="btn btn-sm">Quay lại Tổng quan</Link>}>
        <EmptyState title="Chưa có mục lục" hint="Crawl mục lục trước khi build. Chạy 'Lấy mục lục' ở trang Tổng quan." />
      </Page>
    );
  }

  const metaErrors = data.metadata.filter((m) => m.level === "error");
  const metaWarnings = data.metadata.filter((m) => m.level === "warning");
  const groups = showAllGroups ? data.validation.groups : data.validation.groups.slice(0, 8);
  const canBuild = data.can_build || force;

  return (
    <Page
      title="Build sách"
      hint={
        <span>
          <span className="font-medium">{data.preview.title}</span>
          {data.preview.author ? <span className="opacity-60"> — {data.preview.author}</span> : null} · {num(data.stats.will_include)} chương sẽ vào EPUB
        </span>
      }
      actions={
        <>
          <Link to={`/ebooks/${slug}`} className="btn btn-sm btn-ghost">
            Tổng quan
          </Link>
          <Link to={`/ebooks/${slug}/settings`} className="btn btn-sm btn-ghost">
            <IconSettings size={14} /> Cài đặt
          </Link>
          <Button
            variant="primary"
            icon={<IconPlay size={14} />}
            loading={buildMut.isPending}
            disabled={!canBuild && !force}
            title={!data.can_build && !force ? "Còn blocker — tick 'Bỏ qua validate' để ép build" : "Đóng gói EPUB"}
            onClick={() => buildMut.mutate()}
          >
            Build EPUB
          </Button>
          <Button
            icon={<IconDownload size={14} />}
            disabled={!data.preview.epub.exists}
            title={data.preview.epub.exists ? "Tải EPUB đã build" : "Chưa có EPUB"}
            onClick={() => (window.location.href = apiUrl(`/ebooks/${slug}/download`))}
          >
            Tải EPUB
          </Button>
        </>
      }
    >
      {/* Readiness banner */}
      <div className={clsx("mb-4 rounded-box border px-4 py-3", data.can_build ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5")}>
        <div className="flex flex-wrap items-center gap-3">
          <Dot tone={data.can_build ? "celadon" : data.blocked > 0 ? "vermilion" : "gold"} pulse={!data.can_build} />
          <span className="text-sm font-semibold">
            {data.can_build ? "Sẵn sàng build — đủ điều kiện xuất bản" : `Chưa sẵn sàng — ${data.blocked} chương thiếu bản dịch hoàn chỉnh`}
          </span>
          {data.preview.epub.stale ? <Badge tone="gold">EPUB cũ</Badge> : null}
          {data.preview.epub.exists ? <span className="text-xs opacity-60">· EPUB {bytes(data.preview.epub.size)} · {data.preview.epub.build.finished_at || "chưa rõ thời điểm"}</span> : <Badge tone="neutral">Chưa có EPUB</Badge>}
          <span className="ml-auto flex items-center gap-2 text-xs">
            <label className="flex cursor-pointer items-center gap-1.5">
              <Checkbox checked={force} onChange={(e) => setForce(e.target.checked)} />
              Bỏ qua validate & ép build
            </label>
          </span>
        </div>
        {data.blockers.length > 0 ? (
          <p className="mt-2 text-xs opacity-70">
            Blocker: {data.blockers.slice(0, 5).map((b) => (
              <Link key={b.index} to={`/ebooks/${slug}/chapters/${b.index}`} className="link link-primary mr-2">#{b.index} {b.title.slice(0, 24)}</Link>
            ))}
            {data.blockers.length > 5 ? ` +${data.blockers.length - 5} nữa` : ""}
          </p>
        ) : null}
      </div>

      {/* Stats grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <StatCard label="Tổng chương" value={num(data.stats.total)} hint={`${num(data.stats.skipped)} bỏ qua`} />
        <StatCard label="Sẽ đóng gói" value={num(data.stats.will_include)} hint={`${num(data.stats.will_exclude)} loại`} tone={data.stats.will_include === 0 ? "error" : undefined} />
        <StatCard label="Bị chặn" value={num(data.stats.blocked)} hint={data.blocked ? "Thiếu bản dịch hoàn chỉnh" : "Không có"} tone={data.blocked ? "error" : undefined} />
        <StatCard label="Tổng số từ" value={num(data.stats.word_count)} hint={`TB ${num(data.stats.avg_words)} từ/chương`} />
        <StatCard label="Tổng ký tự" value={num(data.stats.char_count)} hint={`${num(data.stats.han_total)} Hán còn sót`} tone={data.stats.han_total > 50 ? "warning" : undefined} />
        <StatCard label="Chương lỗi" value={num(data.validation.summary.error)} hint={`${num(data.validation.summary.warning)} cảnh báo`} tone={data.validation.summary.error ? "error" : data.validation.summary.warning ? "warning" : undefined} />
      </div>

      {/* Branches */}
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {Object.entries(data.stats.branches).map(([k, v]) => (
          <span key={k} className="rounded-full border border-base-300 bg-base-100 px-2.5 py-1">
            <span className="opacity-60">{v.label}:</span> <strong data-numeric>{num(v.count)}</strong>/{num(data.stats.total - data.stats.skipped)}
            <span className="opacity-50"> ({percent(v.count, Math.max(1, data.stats.total - data.stats.skipped))}%)</span>
          </span>
        ))}
        <span className="rounded-full border border-base-300 bg-base-100 px-2.5 py-1">
          Ngôn ngữ: <strong>{data.preview.language || "vi"}</strong>
        </span>
      </div>

      {/* Metadata completeness */}
      <Panel className="mt-6">
        <PanelHeader title="Thông tin sách" hint={`${metaErrors.length} lỗi · ${metaWarnings.length} cảnh báo`} actions={<Badge tone={metaErrors.length ? "vermilion" : metaWarnings.length ? "gold" : "celadon"}>{metaErrors.length ? "Thiếu bắt buộc" : metaWarnings.length ? "Thiếu khuyến nghị" : "Đầy đủ"}</Badge>} />
        <div className="divide-y divide-base-300">
          <div className="grid gap-3 p-3 sm:grid-cols-3 text-sm">
            <div><span className="opacity-60">Tiêu đề:</span> <span className="font-medium">{data.preview.title || <span className="text-error">— thiếu —</span>}</span></div>
            <div><span className="opacity-60">Tác giả:</span> {data.preview.author || <span className="text-warning">— thiếu —</span>}</div>
            <div><span className="opacity-60">Nhà xuất bản:</span> {data.preview.publisher || <span className="opacity-50">—</span>}</div>
            <div><span className="opacity-60">Bìa:</span> {data.preview.cover.has_cover ? <span className="text-success">Có</span> : <span className="text-warning">Chưa có</span>} <span className="opacity-50 text-xs">{data.preview.cover.cover_file || data.preview.cover.cover_url || ""}</span></div>
            <div><span className="opacity-60">Mục lục:</span> <span className="truncate">{data.preview.toc_url || <span className="text-error">— thiếu —</span>}</span></div>
            <div><span className="opacity-60">EPUB path:</span> <span className="font-mono text-xs break-all">{data.preview.epub.path}</span></div>
          </div>
          {data.metadata.length > 0 ? (
            <ul className="p-3 space-y-1">
              {data.metadata.map((m, i) => (
                <li key={i} className="flex gap-2 text-xs">
                  <Dot tone={levelTone(m.level)} />
                  <span className={clsx(m.level === "error" ? "text-error font-medium" : m.level === "warning" ? "text-warning" : "opacity-70")}>{m.message}</span>
                  {m.hint ? <span className="opacity-50">— {m.hint}</span> : null}
                  {m.field ? <span className="badge badge-xs badge-ghost">{m.field}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-3 text-xs text-success">✓ Metadata đầy đủ</p>
          )}
        </div>
      </Panel>

      {/* Validation groups */}
      <Panel className="mt-6">
        <PanelHeader
          title="Validate nội dung"
          hint={`${data.validation.summary.error} lỗi · ${data.validation.summary.warning} cảnh báo · ${data.validation.summary.info} gợi ý`}
          actions={
            <>
              <Badge tone={data.validation.summary.error ? "vermilion" : data.validation.summary.warning ? "gold" : "neutral"}>
                {data.validation.summary.total_issues} vấn đề
              </Badge>
              {data.validation.groups.length > 8 ? (
                <Button size="sm" variant="ghost" onClick={() => setShowAllGroups((v) => !v)}>{showAllGroups ? "Thu gọn" : `Hiện tất cả ${data.validation.groups.length} nhóm`}</Button>
              ) : null}
            </>
          }
        />
        {data.validation.groups.length === 0 ? (
          <p className="p-6 text-center text-sm opacity-60">✓ Không phát hiện vấn đề về chính tả, mã hóa, dấu lạ</p>
        ) : (
          <div className="divide-y divide-base-300">
            {groups.map((g) => (
              <details key={g.code} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 hover:bg-base-200/50">
                  <Dot tone={levelTone(g.level)} />
                  <span className="font-mono text-xs opacity-60">{g.code}</span>
                  <span className={clsx("text-sm", g.level === "error" ? "text-error" : g.level === "warning" ? "text-warning" : "")}>{g.message}</span>
                  <Badge tone={levelTone(g.level)} className="ml-auto">{num(g.count)} chương</Badge>
                </summary>
                <div className="border-t border-base-300 bg-base-200/30 px-3 py-2">
                  <div className="flex flex-wrap gap-1.5">
                    {g.examples.map((ex) => (
                      <Link key={ex.index} to={`/ebooks/${slug}/chapters/${ex.index}`} className="badge badge-sm badge-ghost hover:badge-primary">
                        #{ex.index} {ex.title.slice(0, 22)}
                      </Link>
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </div>
        )}

        {/* Per-chapter issues */}
        {data.validation.chapters.length > 0 ? (
          <>
            <div className="border-t border-base-300 bg-base-200/20 px-3 py-1.5 text-[11px] font-medium tracking-widest uppercase opacity-60">Chi tiết theo chương · {data.validation.chapters.length} chương có vấn đề</div>
            <div className="max-h-[420px] overflow-auto divide-y divide-base-300">
              {data.validation.chapters.slice(0, 40).map((ch) => (
                <div key={ch.index} className="flex gap-3 px-3 py-2 hover:bg-base-200/30">
                  <Link to={`/ebooks/${slug}/chapters/${ch.index}`} className="shrink-0 font-mono text-xs font-semibold link link-primary">#{ch.index}</Link>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{ch.title || `Chương ${ch.index}`}</p>
                    <ul className="mt-1 space-y-0.5">
                      {ch.issues.map((iss, i) => (
                        <li key={i} className="flex gap-1.5 text-xs">
                          <Dot tone={levelTone(iss.level)} />
                          <span className={clsx(iss.level === "error" ? "text-error" : iss.level === "warning" ? "opacity-80" : "opacity-60")}>{iss.message}</span>
                          {iss.hint ? <span className="opacity-40 hidden sm:inline">— {iss.hint}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <span className="hidden sm:block text-right text-xs opacity-50">
                    <span data-numeric>{num(ch.word_count)} từ</span><br />
                    {ch.han_count ? <span className="text-warning">{ch.han_count} Hán</span> : null}
                  </span>
                </div>
              ))}
            </div>
            {data.validation.chapters.length > 40 ? <p className="border-t border-base-300 px-3 py-2 text-center text-xs opacity-50">… và {data.validation.chapters.length - 40} chương nữa (xem trang Chương để lọc)</p> : null}
          </>
        ) : null}
      </Panel>

      {/* Preview */}
      <Panel className="mt-6">
        <PanelHeader
          title="Preview EPUB"
          hint={`${data.preview.will_include} chương sẽ vào EPUB · ${data.preview.will_exclude} loại · preview ${data.preview.total_preview}/${data.preview.total_will_include}`}
          actions={
            <span className="text-xs opacity-60">
              {data.preview.epub.exists ? <><IconCheck size={12} className="inline text-success" /> Đã có EPUB</> : "Chưa có EPUB"} {data.preview.epub.stale ? "· cũ" : ""}
            </span>
          }
        />
        {/* Cover + TOC */}
        <div className="grid gap-4 p-3 lg:grid-cols-[280px_1fr]">
          <div>
            <p className="mb-2 text-xs font-semibold opacity-60">BÌA & THÔNG TIN</p>
            <div className="rounded-box border border-base-300 bg-base-200/30 p-3">
              {data.preview.cover.has_cover ? (
                <img
                  src={apiUrl(`/ebooks/${slug}/cover`)}
                  alt="Bìa sách"
                  className="mx-auto max-h-64 rounded object-contain"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
                />
              ) : (
                <div className="flex h-32 items-center justify-center rounded bg-base-300/30 text-xs opacity-50">Không có bìa</div>
              )}
              <dl className="mt-3 space-y-1 text-xs">
                <div className="flex justify-between"><dt className="opacity-60">Tiêu đề</dt><dd className="font-medium text-right max-w-[150px] truncate">{data.preview.title}</dd></div>
                <div className="flex justify-between"><dt className="opacity-60">Tác giả</dt><dd className="text-right">{data.preview.author || "—"}</dd></div>
                <div className="flex justify-between"><dt className="opacity-60">Ngôn ngữ</dt><dd>{data.preview.language}</dd></div>
                <div className="flex justify-between"><dt className="opacity-60">EPUB</dt><dd data-numeric>{data.preview.epub.exists ? bytes(data.preview.epub.size) : "—"}</dd></div>
              </dl>
            </div>
          </div>
          <div className="min-w-0">
            <p className="mb-2 flex items-center gap-2 text-xs font-semibold opacity-60">
              MỤC LỤC PREVIEW <span className="font-normal opacity-50">({data.preview.chapters.length} chương đầu)</span>
              <Link to={`/ebooks/${slug}/chapters`} className="ml-auto link link-primary text-[11px]"><IconSearch size={12} className="inline" /> Xem toàn bộ bảng chương</Link>
            </p>
            <div className="overflow-hidden rounded-box border border-base-300">
              <table className="table table-xs">
                <thead>
                  <tr className="bg-base-200/50">
                    <th className="w-14">#</th>
                    <th>Tiêu đề (sẽ vào EPUB)</th>
                    <th className="hidden sm:table-cell">Nhánh</th>
                    <th className="text-right">Từ</th>
                  </tr>
                </thead>
                <tbody>
                  {data.preview.chapters.map((ch) => (
                    <tr key={ch.index} className="hover">
                      <td data-numeric className="font-mono text-xs opacity-60">{ch.index}</td>
                      <td className="min-w-0">
                        <Link to={`/ebooks/${slug}/chapters/${ch.index}`} className="link link-hover line-clamp-1 font-medium text-xs">{ch.title}</Link>
                        <p className="line-clamp-1 text-[11px] opacity-50">{ch.snippet}</p>
                      </td>
                      <td className="hidden sm:table-cell"><Badge tone={ch.branch === "ai" ? "indigo" : "celadon"}>{ch.branch === "ai" ? "AI" : "Local MT"}</Badge></td>
                      <td data-numeric className="text-right text-xs opacity-60">{num(ch.word_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.preview.total_will_include > data.preview.total_preview ? (
                <p className="border-t border-base-300 bg-base-200/30 px-3 py-2 text-center text-xs opacity-60">… và {data.preview.total_will_include - data.preview.total_preview} chương nữa sẽ được đóng gói</p>
              ) : null}
            </div>

            {/* Encoding / spelling highlights in preview */}
            <div className="mt-3 rounded-box border border-base-300 bg-amber-50/40 px-3 py-2.5 dark:bg-amber-950/20">
              <p className="text-xs font-semibold">Lưu ý trước khi build</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs opacity-70">
                <li>Validate kiểm tra: mã hóa (�, control chars, mojibake), dấu lạ (##, ```, .., !!, …), chính tả (double-space, thừa/thiếu space sau dấu câu, từ lặp), chữ Hán còn sót.</li>
                <li>Nếu muốn bỏ qua cảnh báo và build ngay, tick “Bỏ qua validate & ép build”.</li>
                <li>Chương “bỏ qua” (skipped) và chương chưa có bản dịch hoàn chỉnh sẽ không vào EPUB.</li>
              </ul>
            </div>
          </div>
        </div>
      </Panel>

      <p className="mt-4 text-center text-xs opacity-40">
        Preview chỉ đọc DB, không gọi AI. Build thực sẽ đóng gói bằng <code className="rounded bg-base-200 px-1">pipeline.step_build_selected</code> và ghi <code className="rounded bg-base-200 px-1">{data.preview.epub.path}</code>
      </p>
    </Page>
  );
}
