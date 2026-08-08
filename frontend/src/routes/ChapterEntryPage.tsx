import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";

import { firstReadingIndex } from "@/lib/chapter";
import { Spinner } from "@/components/ui/Button";

const bookmarkKey = (slug: string) => `n2e-bookmark-${slug}`;

/** `/ebooks/:slug/read` — nhảy tới bookmark đã lưu, hoặc chương đầu có bản dịch. */
export function ChapterEntryPage() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const bookmarked = Number(localStorage.getItem(bookmarkKey(slug)));
    if (Number.isFinite(bookmarked) && bookmarked > 0) {
      navigate(`/ebooks/${slug}/chapters/${bookmarked}`, { replace: true });
      return;
    }
    firstReadingIndex(slug)
      .then((index) => {
        if (!cancelled) navigate(`/ebooks/${slug}/chapters/${index}`, { replace: true });
      })
      .catch(() => {
        if (!cancelled) navigate(`/ebooks/${slug}`, { replace: true });
      });
    return () => {
      cancelled = true;
    };
  }, [slug, navigate]);

  return (
    <div className="flex min-h-[70vh] items-center justify-center gap-2 text-sm opacity-60">
      <Spinner /> Đang mở chương đọc gần nhất
    </div>
  );
}
