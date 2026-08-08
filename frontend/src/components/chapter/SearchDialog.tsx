import { useState } from "react";

import { useBookSearch } from "@/lib/chapter";
import { num } from "@/lib/format";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Button";
import { Checkbox, InputWithIcon } from "@/components/ui/Field";
import { IconSearch } from "@/components/icons";

export function SearchDialog({
  open,
  onClose,
  slug,
  onJump,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  onJump: (index: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);

  const { data, isFetching, error } = useBookSearch(slug, submitted, regex, caseSensitive);

  return (
    <Modal open={open} onClose={onClose} title="Tìm trong toàn bộ chương đã dịch" wide>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
        className="flex flex-wrap items-center gap-3"
      >
        <InputWithIcon
          icon={<IconSearch size={14} />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Chuỗi cần tìm"
          className="min-w-[14rem] flex-1"
          autoFocus
        />
        <label className="flex items-center gap-1.5 text-[13px] opacity-70">
          <Checkbox checked={regex} onChange={(e) => setRegex(e.target.checked)} /> Regex
        </label>
        <label className="flex items-center gap-1.5 text-[13px] opacity-70">
          <Checkbox checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />{" "}
          Hoa/thường
        </label>
        <button type="submit" className="btn btn-sm btn-primary">
          Tìm
        </button>
      </form>

      <div className="scroll-slim mt-3 max-h-[55vh] overflow-y-auto">
        {isFetching ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : error ? (
          <p className="py-4 text-center text-xs text-error">
            {error instanceof Error ? error.message : String(error)}
          </p>
        ) : !submitted ? (
          <p className="py-8 text-center text-xs opacity-50">
            Nhập chuỗi cần tìm rồi bấm Tìm hoặc Enter.
          </p>
        ) : data && data.length === 0 ? (
          <p className="py-8 text-center text-xs opacity-50">Không tìm thấy kết quả nào.</p>
        ) : (
          <ul className="space-y-1">
            {(data ?? []).map((hit) => (
              <li key={hit.chapter_index}>
                <button
                  type="button"
                  onClick={() => {
                    onJump(hit.chapter_index);
                    onClose();
                  }}
                  className="w-full rounded-field px-2.5 py-2 text-left hover:bg-base-200"
                >
                  <span className="text-[13px] font-medium">
                    {hit.title}
                    <span data-numeric className="ml-1.5 text-xs text-primary">
                      {num(hit.count)}
                    </span>
                  </span>
                  {hit.snippets.map((s, i) => (
                    <span key={i} className="mt-0.5 block truncate text-xs opacity-60">
                      {s}
                    </span>
                  ))}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
