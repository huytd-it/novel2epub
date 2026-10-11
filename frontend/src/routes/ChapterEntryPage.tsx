import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";

import { firstReadingIndex, readReadingPosition } from "@/lib/chapter";
import { Loading } from "@/components/ui/Loading";

const bookmarkKey = (slug: string) => `n2e-bookmark-${slug}`;

/** `/ebooks/:slug/read` — nhảy tới vị trí đọc gần nhất, bookmark hoặc chương đầu. */
export function ChapterEntryPage() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const position = readReadingPosition(slug);
    if (position) {
      navigate(`/ebooks/${slug}/chapters/${position.chapterIndex}`, {
        replace: true,
        state: { restoreReadingPosition: true },
      });
      return;
    }
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
    <Loading size="lg" label="Đang mở chương đọc gần nhất" className="min-h-[70vh]" />
  );
}
