import { useMemo, useState } from "react";
import { Link } from "react-router";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { InputWithIcon } from "@/components/ui/Field";
import { Badge } from "@/components/ui/Badge";
import {
  IconBook,
  IconChip,
  IconClock,
  IconDisk,
  IconLanguages,
  IconSearch,
  IconShield,
  IconSource,
  IconTailscale,
  IconPlug,
} from "@/components/icons";
import { PiCaretRight } from "react-icons/pi";

type Card = {
  to: string;
  label: string;
  desc: string;
  keywords: string;
  icon: typeof IconSource;
  group: string;
  tone: "indigo" | "celadon" | "gold" | "neutral" | "vermilion";
};

const CARDS: Card[] = [
  {
    to: "/translate-settings",
    label: "Dịch chung",
    desc: "Prompt, văn phong, giới hạn token/chunk, retry và glossary mặc định cho mọi truyện.",
    keywords: "dich chung prompt translate defaults genre tone pronoun han viet",
    icon: IconLanguages,
    group: "Dịch thuật",
    tone: "indigo",
  },
  {
    to: "/local-mt",
    label: "Local MT chung",
    desc: "Model NMT cục bộ — chọn HachimiMT, beam, chunk mode và tải/cập nhật model.",
    keywords: "local mt hachimi ctranslate2 model beam chunk offline",
    icon: IconChip,
    group: "Dịch thuật",
    tone: "celadon",
  },
  {
    to: "/idioms",
    label: "Từ điển chung",
    desc: "Kho thành ngữ Hán-Việt dùng chung — thay bản máy thành bản đẹp cho mọi pipeline.",
    keywords: "tu dien thanh ngu idioms han viet protect literals",
    icon: IconBook,
    group: "Dịch thuật",
    tone: "gold",
  },
  {
    to: "/sources",
    label: "Nguồn",
    desc: "Preset crawl: wrapper selector, regex lọc link, chế độ Scrapling, delay & proxy.",
    keywords: "nguon source preset selector regex crawl scrapling toc chapter",
    icon: IconSource,
    group: "Crawl & Nguồn",
    tone: "neutral",
  },
  {
    to: "/automation",
    label: "Tự động hóa",
    desc: "Pipeline cron: cào → dịch → build theo lịch, theo dõi log từng bước.",
    keywords: "tu dong hoa automation cron pipeline schedule",
    icon: IconClock,
    group: "Crawl & Nguồn",
    tone: "indigo",
  },
  {
    to: "/storage",
    label: "Lưu trữ",
    desc: "Dung lượng raw / translated / glossary / EPUB theo truyện — dọn archive khi cần.",
    keywords: "luu tru storage disk dung luong raw translated epub archive",
    icon: IconDisk,
    group: "Vận hành",
    tone: "celadon",
  },
  {
    to: "/connection",
    label: "Kết nối",
    desc: "Cấu hình API base, token, CORS — chuyển giữa cùng origin, tailnet hay Funnel.",
    keywords: "ket noi connection api base token cors tailnet funnel",
    icon: IconPlug,
    group: "Vận hành",
    tone: "neutral",
  },
  {
    to: "/wireguard",
    label: "WireGuard",
    desc: "Quản lý tunnel WireGuard — cấu hình, trạng thái và kết nối VPN.",
    keywords: "wireguard vpn tunnel",
    icon: IconShield,
    group: "Mạng",
    tone: "vermilion",
  },
  {
    to: "/tailscale",
    label: "Tailscale",
    desc: "Mạng tailnet — trạng thái node, key và kết nối tới backend qua Tailscale.",
    keywords: "tailscale tailnet vpn",
    icon: IconTailscale,
    group: "Mạng",
    tone: "indigo",
  },
];

const GROUPS = ["Tất cả", "Dịch thuật", "Crawl & Nguồn", "Vận hành", "Mạng"] as const;

export function SystemPage() {
  const [q, setQ] = useState("");
  const [group, setGroup] = useState<(typeof GROUPS)[number]>("Tất cả");

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return CARDS.filter((c) => {
      const matchGroup = group === "Tất cả" || c.group === group;
      if (!matchGroup) return false;
      if (!needle) return true;
      const hay = `${c.label} ${c.desc} ${c.keywords} ${c.group}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [q, group]);

  return (
    <Page
      title="Hệ thống"
      hint="Trung tâm cấu hình & vận hành — 9 trang quản lý gom một chỗ, gõ để lọc nhanh"
      actions={
        <span className="hidden sm:inline-flex items-center gap-2 text-xs opacity-60">
          <span data-numeric>{filtered.length}</span>/<span data-numeric>{CARDS.length}</span> mục
        </span>
      }
    >
      {/* Search + filter */}
      <div className="mb-4 flex flex-col gap-3 rounded-box border border-base-300 bg-base-100 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 items-center gap-3">
          <InputWithIcon
            icon={<IconSearch size={14} />}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm theo tên, mô tả, từ khóa… (vd: prompt, cron, vpn)"
            className="w-full sm:max-w-md"
            aria-label="Tìm trong Hệ thống"
          />
          {q ? (
            <button
              type="button"
              onClick={() => setQ("")}
              className="btn btn-ghost btn-xs shrink-0"
            >
              Xóa
            </button>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {GROUPS.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => setGroup(g)}
              className={clsx(
                "btn btn-xs rounded-full",
                group === g ? "btn-primary" : "btn-ghost border border-base-300",
              )}
            >
              {g}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <div className="rounded-box border border-dashed border-base-300 bg-base-100 p-10 text-center">
          <p className="text-sm font-medium">Không có mục nào khớp “{q}”</p>
          <p className="mt-1 text-xs opacity-60">Thử từ khóa khác hoặc chọn nhóm khác.</p>
          <button type="button" onClick={() => { setQ(""); setGroup("Tất cả"); }} className="btn btn-sm mt-3">
            Xóa bộ lọc
          </button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((card) => {
            const Icon = card.icon;
            return (
              <Link
                key={card.to}
                to={card.to}
                className="group relative flex flex-col rounded-box border border-base-300 bg-base-100 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg hover:shadow-base-300/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-base-200 text-base-content/70 transition-colors duration-200 group-hover:bg-primary/10 group-hover:text-primary">
                    <Icon size={18} />
                  </span>
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-base-300 bg-base-100 text-base-content/40 transition-all duration-200 group-hover:border-primary/20 group-hover:bg-primary group-hover:text-primary-content group-hover:translate-x-0.5">
                    <PiCaretRight size={12} />
                  </span>
                </div>

                <h3 className="mt-3 font-display text-[15px] font-semibold leading-tight tracking-tight">
                  {card.label}
                </h3>
                <p className="mt-1.5 line-clamp-2 text-[13px] leading-relaxed opacity-60">
                  {card.desc}
                </p>

                <div className="mt-3 flex items-center gap-1.5">
                  <Badge tone={card.tone} className="text-[10px] leading-none">
                    {card.group}
                  </Badge>
                  <span className="truncate font-mono text-[11px] opacity-35">{card.to}</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <p className="mt-4 text-center text-[11px] opacity-40">
        Mẹo: gõ “vpn” để thấy WireGuard & Tailscale · gõ “prompt” để tới Dịch chung
      </p>
    </Page>
  );
}
