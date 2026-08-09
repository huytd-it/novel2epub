import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import clsx from "clsx";

import { useTheme } from "@/lib/theme";
import { pendingCount, useQueue } from "@/lib/queue";
import { useCurrentBook, useLibrary } from "@/lib/books";
import { legacyUrl } from "@/lib/api";
import { num } from "@/lib/format";
import { ChapterStrip } from "@/components/ChapterStrip";
import { decodeStrip } from "@/lib/strip";
import {
  IconBook,
  IconCharacters,
  IconChevronLeft,
  IconChevronRight,
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

/** Trang của một truyện đã port sang SPA.
 *
 * `end: false` cho "Chương": trang chương thật nằm ở `/chapters/:index` (route
 * anh em, không phải route con của `/chapters`), nên phải khớp theo tiền tố
 * mới giữ được mục này sáng khi đang mở dở một chương.
 */
function bookRoutes(slug: string) {
  return [
    { to: `/ebooks/${slug}`, label: "Tổng quan", icon: IconOverview, end: true },
    { to: `/ebooks/${slug}/chapters`, label: "Chương", icon: IconRead, end: false },
    { to: `/ebooks/${slug}/glossary`, label: "Glossary", icon: IconGlossary, end: true },
    { to: `/ebooks/${slug}/characters`, label: "Nhân vật", icon: IconCharacters, end: true },
    { to: `/ebooks/${slug}/settings`, label: "Cài đặt", icon: IconSettings, end: true },
  ];
}

/** Phần trang Jinja2 cũ chưa port — hiện không còn mục nào, giữ hàm để dễ
 * thêm lại khi có trang mới cần đánh dấu "mở ở tab khác". */
function bookLegacyLinks(_slug: string): { href: string; label: string; icon: typeof IconRead }[] {
  return [];
}

const navItem =
  "group min-h-9 w-full gap-2.5 rounded-field px-3 py-2 text-[13px] transition-colors duration-150 hover:bg-base-200/80";

function GroupTitle({ children, collapsed }: { children: React.ReactNode; collapsed?: boolean }) {
  return (
    <h2
      className={clsx(
        "menu-title px-2 pt-2 pb-1.5 text-[10px] tracking-[0.12em] uppercase opacity-55",
        collapsed && "sr-only",
      )}
    >
      {children}
    </h2>
  );
}

/** Mục điều hướng dùng chung: khi `collapsed` bọc icon trong nút tròn + tooltip. */
function SidebarLink({
  to,
  end,
  label,
  icon: Icon,
  collapsed,
  trailing,
}: {
  to: string;
  end?: boolean;
  label: string;
  icon: typeof IconLibrary;
  collapsed: boolean;
  trailing?: React.ReactNode;
}) {
  if (collapsed) {
    return (
      <li className="relative flex flex-row items-center justify-center py-1">
        <NavLink
          to={to}
          end={end}
          title={label}
          aria-label={label}
          className={({ isActive }) =>
            clsx(
              "flex size-10 items-center justify-center rounded-full ring-1 transition-[background-color,color,box-shadow] duration-150",
              isActive
                ? "bg-primary/15 text-primary ring-primary/30 shadow-sm"
                : "text-base-content/65 ring-transparent hover:bg-base-200 hover:text-base-content hover:ring-base-300",
            )
          }
        >
          <Icon size={18} className="shrink-0" />
        </NavLink>
        {trailing}
      </li>
    );
  }

  return (
    <li className="px-1.5 py-0.5">
      <NavLink
        to={to}
        end={end}
        title={label}
        className={({ isActive }) =>
          clsx(
            navItem,
            isActive
              ? "bg-base-200 font-medium text-base-content shadow-[inset_0_0_0_1px_var(--color-base-300)]"
              : "text-base-content/72",
          )
        }
      >
        <Icon size={17} className="shrink-0 opacity-75 transition-opacity group-hover:opacity-100" />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {trailing}
      </NavLink>
    </li>
  );
}

/* ── Truyện đang làm ─────────────────────────────────────────────────── */

function BookSection({ collapsed }: { collapsed: boolean }) {
  const [slug] = useCurrentBook();
  const { data } = useLibrary();
  const book = data?.ebooks.find((b) => b.slug === slug);
  const states = useMemo(() => decodeStrip(book?.strip ?? ""), [book?.strip]);

  return (
    <li>
      <GroupTitle collapsed={collapsed}>Đang làm</GroupTitle>

      {book ? (
        <>
          {!collapsed ? (
            book.total > 0 ? (
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
            )
          ) : null}
          <ul className="!ms-0 !ps-0">
            {bookRoutes(book.slug).map(({ to, label, icon: Icon, end }) => (
              <SidebarLink
                key={to}
                to={to}
                end={end}
                label={label}
                icon={Icon}
                collapsed={collapsed}
              />
            ))}
            {!collapsed
              ? bookLegacyLinks(book.slug).map(({ href, label, icon: Icon }) => (
                  <li key={href} className="px-1.5 py-0.5">
                    <a href={legacyUrl(href)} className={navItem} title={label}>
                      <Icon size={17} className="shrink-0 opacity-75" />
                      <span className="min-w-0 flex-1 truncate">{label}</span>
                      <IconExternal size={11} className="shrink-0 opacity-35" />
                    </a>
                  </li>
                ))
              : null}
          </ul>
        </>
      ) : null}
    </li>
  );
}

/* ── Điều hướng toàn cục ─────────────────────────────────────────────── */

/** Đếm việc chạy/chờ ngay trên mục Hàng đợi — không cần ô đo riêng nữa. */
function QueueCount({ collapsed }: { collapsed: boolean }) {
  const { data } = useQueue();
  const running = data?.running.length ?? 0;
  const waiting = pendingCount(data);
  if (!running && !waiting) return null;

  if (collapsed) {
    return (
      <span className="absolute right-1 top-1.5" aria-hidden="true">
        <span
          className={clsx(
            "block size-1.5 rounded-full",
            running ? "bg-warning pulse-run" : "bg-base-300",
          )}
        />
      </span>
    );
  }

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

function WorkshopSection({ collapsed }: { collapsed: boolean }) {
  return (
    <li>
      <GroupTitle collapsed={collapsed}>Xưởng</GroupTitle>
      <ul className="!ms-0 !ps-0">
        {WORKSHOP.map(({ to, label, icon: Icon, end }) => (
          <SidebarLink
            key={to}
            to={to}
            end={end}
            label={label}
            icon={Icon}
            collapsed={collapsed}
            trailing={to === "/queue" ? <QueueCount collapsed={collapsed} /> : undefined}
          />
        ))}
      </ul>
    </li>
  );
}

function SystemSection({ open, collapsed }: { open: boolean; collapsed: boolean }) {
  return (
    <li>
      {/* Nhóm này hiếm khi dùng — thu lại để phần "đang làm" luôn nằm trên nếp gấp. */}
      <details open={open || collapsed}>
        <summary
          title="Mở hoặc đóng nhóm Hệ thống"
          className={clsx(
            "mx-1.5 mt-2 rounded-field px-2 py-1.5 text-[10px] font-semibold tracking-[0.12em] uppercase opacity-55 transition-colors hover:bg-base-200 hover:opacity-80",
            collapsed && "sr-only",
          )}
        >
          Hệ thống
        </summary>
        <ul className="!ms-0 !ps-0">
          {SYSTEM.map(({ to, label, icon: Icon }) => (
            <SidebarLink key={to} to={to} label={label} icon={Icon} collapsed={collapsed} />
          ))}
        </ul>
      </details>
    </li>
  );
}

export function Shell() {
  const [theme, toggleTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem("n2e-sidebar-collapsed") === "1";
    } catch {
      return false;
    }
  });
  const location = useLocation();
  const inSystem = SYSTEM.some((item) => location.pathname.startsWith(item.to));

  useEffect(() => setDrawer(false), [location.pathname]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("n2e-sidebar-collapsed", next ? "1" : "0");
      } catch {
        /* bỏ qua khi không truy cập được localStorage */
      }
      return next;
    });
  };

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
        <aside
          className={clsx(
            "flex h-full min-h-screen flex-col border-r border-base-300 bg-base-100 transition-[width] duration-200",
            collapsed ? "w-16" : "w-64",
          )}
        >
          <div
            className={clsx(
              "flex h-13 shrink-0 items-center",
              collapsed ? "justify-center px-2" : "gap-2 px-3.5",
            )}
          >
            {!collapsed ? (
              <>
                <span className="font-display text-[15px] font-semibold tracking-tight">
                  novel2epub
                </span>
                <span className="badge badge-xs badge-ghost">xưởng</span>
              </>
            ) : null}
            <button
              type="button"
              onClick={toggleCollapsed}
              title={collapsed ? "Mở rộng menu bên" : "Thu gọn menu bên"}
              aria-label={collapsed ? "Mở rộng menu bên" : "Thu gọn menu bên"}
              className={clsx(
                "btn btn-ghost btn-sm btn-circle text-base-content/60 hover:bg-base-200 hover:text-base-content",
                !collapsed && "ml-auto",
              )}
            >
              {collapsed ? <IconChevronRight size={14} /> : <IconChevronLeft size={14} />}
            </button>
          </div>

          <ul className="menu menu-sm scroll-slim w-full flex-1 flex-nowrap overflow-y-auto px-1 py-1">
            <BookSection collapsed={collapsed} />
            <li role="separator" aria-hidden="true" className="mx-2 my-2 h-px bg-base-300/70" />
            <WorkshopSection collapsed={collapsed} />
            <SystemSection open={inSystem} collapsed={collapsed} />
          </ul>

          <div
            className={clsx(
              "mx-2 mb-2 flex shrink-0 items-center rounded-field bg-base-200/55 py-1.5",
              collapsed ? "justify-center" : "justify-between px-2",
            )}
          >
            {!collapsed ? <span className="text-[11px] opacity-55">Giao diện</span> : null}
            <button
              type="button"
              onClick={toggleTheme}
              title={theme === "dark" ? "Chuyển sang nền sáng" : "Chuyển sang nền tối"}
              aria-label={theme === "dark" ? "Chuyển sang nền sáng" : "Chuyển sang nền tối"}
              className="btn btn-ghost btn-sm btn-circle text-base-content/65 hover:bg-base-300/70 hover:text-base-content"
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
