import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import clsx from "clsx";

import { useTheme } from "@/lib/theme";
import { pendingCount, useQueue } from "@/lib/queue";
import { useCurrentBook, useLibrary } from "@/lib/books";
import { legacyUrl } from "@/lib/api";
import { num, percent } from "@/lib/format";
import { ChapterStrip } from "@/components/ChapterStrip";
import { decodeStrip } from "@/lib/strip";
import {
  IconBook,
  IconCharacters,
  IconCheck,
  IconClock,
  IconDisk,
  IconExternal,
  IconGauge,
  IconGlossary,
  IconLibrary,
  IconLog,
  IconMenu,
  IconMoon,
  IconOverview,
  IconPlug,
  IconQueue,
  IconRead,
  IconSettings,
  IconShield,
  IconSource,
  IconSun,
  IconSwitch,
} from "@/components/icons";

type Item = { to: string; label: string; icon: typeof IconLibrary; end?: boolean };

const WORKSHOP: Item[] = [
  { to: "/", label: "Thư viện", icon: IconLibrary, end: true },
  { to: "/dashboard", label: "Bảng điều khiển", icon: IconGauge },
  { to: "/queue", label: "Hàng đợi", icon: IconQueue },
  { to: "/logs", label: "Nhật ký", icon: IconLog },
];

const SYSTEM: Item[] = [
  { to: "/sources", label: "Nguồn", icon: IconSource },
  { to: "/idioms", label: "Từ điển chung", icon: IconBook },
  { to: "/automation", label: "Tự động hóa", icon: IconClock },
  { to: "/storage", label: "Lưu trữ", icon: IconDisk },
  { to: "/wireguard", label: "WireGuard", icon: IconShield },
  { to: "/connection", label: "Kết nối", icon: IconPlug },
];

/** Trang của một truyện đã port sang SPA. */
function bookRoutes(slug: string) {
  return [{ to: `/ebooks/${slug}`, label: "Tổng quan", icon: IconOverview }];
}

/** Phần còn lại vẫn là giao diện Jinja2 cũ — đánh dấu bằng icon rời trang. */
function bookLegacyLinks(slug: string) {
  return [
    { href: `/ebooks/${slug}/read`, label: "Đọc", icon: IconRead },
    { href: `/ebooks/${slug}/glossary`, label: "Glossary", icon: IconGlossary },
    { href: `/ebook/${slug}/characters`, label: "Nhân vật", icon: IconCharacters },
    { href: `/ebooks/${slug}/settings`, label: "Cài đặt", icon: IconSettings },
  ];
}

const navItem = "group gap-2.5 rounded-field text-[13px]";

function GroupTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="menu-title px-3 pb-1 text-[10px] tracking-[0.12em] uppercase">{children}</h2>
  );
}

/* ── Truyện đang làm ─────────────────────────────────────────────────── */

function BookSwitcher() {
  const [slug, select] = useCurrentBook();
  const { data } = useLibrary();
  const books = data?.ebooks ?? [];
  const active = books.find((b) => b.slug === slug);

  return (
    <div className="dropdown dropdown-bottom w-full">
      <div
        tabIndex={0}
        role="button"
        className="btn btn-sm w-full justify-between border-base-300 bg-base-200 font-normal"
      >
        <span className="truncate">{active ? active.name : "Chọn truyện"}</span>
        <IconSwitch size={14} className="shrink-0 opacity-60" />
      </div>
      <ul className="dropdown-content menu menu-sm scroll-slim z-50 max-h-80 w-64 flex-nowrap overflow-y-auto rounded-box border border-base-300 bg-base-100 shadow-lg">
        {books.length === 0 ? (
          <li className="px-3 py-2 text-xs opacity-60">Thư viện đang trống</li>
        ) : (
          books.map((b) => (
            <li key={b.slug}>
              <button type="button" onClick={() => select(b.slug)} className="justify-between">
                <span className="truncate">{b.name}</span>
                <span className="flex shrink-0 items-center gap-1.5">
                  <span data-numeric className="text-[11px] opacity-50">
                    {percent(b.translated_count, b.total)}%
                  </span>
                  {b.slug === slug ? <IconCheck size={13} className="text-primary" /> : null}
                </span>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

function BookSection() {
  const [slug] = useCurrentBook();
  const { data } = useLibrary();
  const book = data?.ebooks.find((b) => b.slug === slug);
  const states = useMemo(() => decodeStrip(book?.strip ?? ""), [book?.strip]);

  return (
    <li>
      <GroupTitle>Đang làm</GroupTitle>
      <div className="px-2 pb-1">
        <BookSwitcher />
      </div>

      {book ? (
        <>
          {book.total > 0 ? (
            <div className="px-3 pt-1 pb-2">
              <ChapterStrip states={states} height={8} />
              <p className="mt-1.5 text-[11px] opacity-60">
                <span data-numeric className="font-medium opacity-100">
                  {num(book.translated_count)}
                </span>
                <span data-numeric className="opacity-70">
                  /{num(book.total)}
                </span>{" "}
                chương đã dịch
              </p>
            </div>
          ) : (
            <p className="px-3 pt-1 pb-2 text-[11px] opacity-50">Chưa có mục lục.</p>
          )}
          <ul>
            {bookRoutes(book.slug).map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end
                  className={({ isActive }) =>
                    clsx(
                      navItem,
                      "border-l-2",
                      isActive ? "menu-active border-primary font-medium" : "border-transparent",
                    )
                  }
                >
                  <Icon size={16} className="shrink-0 opacity-70" />
                  <span className="truncate">{label}</span>
                </NavLink>
              </li>
            ))}
            {bookLegacyLinks(book.slug).map(({ href, label, icon: Icon }) => (
              <li key={href}>
                <a href={legacyUrl(href)} className={navItem}>
                  <Icon size={16} className="shrink-0 opacity-70" />
                  <span className="truncate">{label}</span>
                  <IconExternal size={11} className="ml-auto shrink-0 opacity-25" />
                </a>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </li>
  );
}

/* ── Điều hướng toàn cục ─────────────────────────────────────────────── */

/** Đếm việc chạy/chờ ngay trên mục Hàng đợi — không cần ô đo riêng nữa. */
function QueueCount() {
  const { data } = useQueue();
  const running = data?.running.length ?? 0;
  const waiting = pendingCount(data);
  if (!running && !waiting) return null;

  return (
    <span className="ml-auto flex shrink-0 items-center gap-1">
      {running ? (
        <span className="size-1.5 rounded-full bg-warning pulse-run" aria-hidden="true" />
      ) : null}
      <span data-numeric className="text-[11px]">
        <span className={running ? "text-warning" : "opacity-50"}>{running}</span>
        <span className="opacity-40">/{waiting}</span>
      </span>
    </span>
  );
}

function WorkshopSection() {
  return (
    <li>
      <GroupTitle>Xưởng</GroupTitle>
      <ul>
        {WORKSHOP.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  navItem,
                  "border-l-2",
                  isActive ? "menu-active border-primary font-medium" : "border-transparent",
                )
              }
            >
              <Icon size={16} className="shrink-0 opacity-70" />
              <span className="truncate">{label}</span>
              {to === "/queue" ? <QueueCount /> : null}
            </NavLink>
          </li>
        ))}
      </ul>
    </li>
  );
}

function SystemSection({ open }: { open: boolean }) {
  return (
    <li>
      {/* Nhóm này hiếm khi dùng — thu lại để phần "đang làm" luôn nằm trên nếp gấp. */}
      <details open={open}>
        <summary className="px-3 text-[10px] font-semibold tracking-[0.12em] uppercase opacity-60">
          Hệ thống
        </summary>
        <ul>
          {SYSTEM.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  clsx(
                    navItem,
                    "border-l-2",
                    isActive ? "menu-active border-primary font-medium" : "border-transparent",
                  )
                }
              >
                <Icon size={16} className="shrink-0 opacity-70" />
                <span className="truncate">{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}

export function Shell() {
  const [theme, toggleTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const inSystem = SYSTEM.some((item) => location.pathname.startsWith(item.to));

  useEffect(() => setDrawer(false), [location.pathname]);

  return (
    <div className="drawer md:drawer-open">
      <input
        id="n2e-drawer"
        type="checkbox"
        className="drawer-toggle"
        checked={drawer}
        onChange={(e) => setDrawer(e.target.checked)}
      />

      <div className="drawer-content flex min-h-screen min-w-0 flex-col">
        <div className="sticky top-0 z-40 flex h-12 items-center gap-2 border-b border-base-300 bg-base-200/90 px-3 backdrop-blur md:hidden">
          <label
            htmlFor="n2e-drawer"
            className="btn btn-ghost btn-sm btn-square"
            aria-label="Mở menu"
          >
            <IconMenu size={18} />
          </label>
          <span className="font-display text-sm font-semibold">novel2epub</span>
        </div>
        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>

      <div className="drawer-side z-90">
        <label htmlFor="n2e-drawer" className="drawer-overlay" aria-label="Đóng menu" />
        <aside className="flex h-full min-h-screen w-64 flex-col border-r border-base-300 bg-base-100">
          <div className="flex h-12 shrink-0 items-center gap-2 px-4">
            <span className="font-display text-[15px] font-semibold tracking-tight">
              novel2epub
            </span>
            <span className="badge badge-xs badge-ghost">xưởng</span>
          </div>

          <ul className="menu menu-sm scroll-slim w-full flex-1 flex-nowrap overflow-y-auto">
            <BookSection />
            <div className="divider my-1 h-px" />
            <WorkshopSection />
            <SystemSection open={inSystem} />
          </ul>

          <div className="flex shrink-0 items-center justify-between border-t border-base-300 px-4 py-2">
            <span className="text-[11px] opacity-60">Giao diện</span>
            <button
              type="button"
              onClick={toggleTheme}
              className="btn btn-ghost btn-xs btn-square"
              aria-label={theme === "dark" ? "Chuyển sang nền sáng" : "Chuyển sang nền tối"}
            >
              {theme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

export function Page({
  title,
  hint,
  actions,
  children,
}: {
  title: string;
  hint?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 py-5 md:px-6">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-2xl leading-tight">{title}</h1>
          {hint ? <p className="mt-1 text-[13px] opacity-60">{hint}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </header>
      {children}
    </div>
  );
}
