// Shell dùng chung mọi trang: theme toggle (persist localStorage), toast
// helper, queue indicator poll /api/queue, modal/canvas/tab helpers.

function toast(message, kind = "info") {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const el = document.createElement("div");
    const base = "flex items-center gap-2 rounded-lg border bg-surface-light dark:bg-surface-dark text-fg-light dark:text-fg-dark text-sm shadow-card dark:shadow-card-dark transition-all duration-normal pointer-events-auto";
    const variant = kind === "error"
        ? " border-status-err-fg"
        : kind === "success"
        ? " border-status-ok-fg"
        : kind === "warning"
        ? " border-status-warn-fg"
        : " border-surface-border dark:border-surface-border-dark";
    el.className = base + variant + " opacity-0 translate-y-2";
    const iconName = kind === "error" ? "circle-x" : kind === "success" ? "circle-check" : kind === "warning" ? "triangle-alert" : "info";
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("width", "16");
    icon.setAttribute("height", "16");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("fill", "none");
    icon.setAttribute("stroke", "currentColor");
    icon.setAttribute("stroke-width", "2");
    icon.setAttribute("stroke-linecap", "round");
    icon.setAttribute("stroke-linejoin", "round");
    icon.classList.add("flex-shrink-0");
    icon.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#lucide-${iconName}`);
    icon.appendChild(use);
    const text = document.createElement("span");
    text.textContent = String(message);
    el.append(icon, text);
    region.appendChild(el);
    if (window.lucide) lucide.createIcons();
    requestAnimationFrame(() => {
        el.classList.remove("opacity-0", "translate-y-2");
        el.classList.add("opacity-100", "translate-y-0");
    });
    setTimeout(() => {
        el.classList.remove("opacity-100", "translate-y-0");
        el.classList.add("opacity-0", "translate-y-2");
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

(function initTheme() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
        const root = document.documentElement;
        const isDark = root.classList.toggle("dark");
        const next = isDark ? "dark" : "light";
        root.setAttribute("data-theme", next);
        localStorage.setItem("n2e-theme", next);
        updateThemeIcons(isDark);
    });
    // Initial icon state
    const isDark = document.documentElement.classList.contains("dark");
    updateThemeIcons(isDark);
})();

function updateThemeIcons(isDark) {
    const sunIcon = document.querySelector(".icon-sun");
    const moonIcon = document.querySelector(".icon-moon");
    if (sunIcon && moonIcon) {
        sunIcon.style.display = isDark ? "block" : "none";
        moonIcon.style.display = isDark ? "none" : "block";
    }
}

(function initQueueIndicator() {
    const countEl = document.getElementById("queue-count-header") || document.getElementById("queue-count");
    if (!countEl) return;

    async function poll() {
        try {
            const res = await fetch("/api/queue");
            if (!res.ok) return;
            const data = await res.json();
            const pendingTotal = Object.values(data.pending || {}).reduce((n, arr) => n + arr.length, 0);
            const total = (data.running || []).length + pendingTotal;
            countEl.textContent = total;
            const indicator = document.getElementById("queue-indicator");
            if (indicator) {
                const active = total > 0;
                indicator.classList.toggle("border-brand-500", active);
                indicator.classList.toggle("bg-brand-50", active);
                indicator.classList.toggle("text-brand-700", active);
                indicator.classList.toggle("dark:bg-brand-950/30", active);
                indicator.classList.toggle("dark:text-brand-300", active);
            }
        } catch (e) {
            // Silent: trang chưa có /api/queue không nên báo lỗi ồn ào.
        }
    }

    poll();
    setInterval(poll, 3000);
})();

// --- AJAX form helper -------------------------------------------------------
// Any <form data-ajax> submits via fetch instead of navigating, so background
// actions (delete/purge/run-now/create…) never reload the whole page. Opt-in
// data-attributes on the form:
//   data-confirm="msg"        → in-app confirmation before sending
//   data-toast="msg"          → success toast
//   data-ajax-reload="#id"    → after success, swap that region with the fresh
//                               copy from the response (routes 303-redirect to
//                               the page, which fetch follows → we get its HTML)
//   data-close-modal="id"     → closeModal(id) on success
//   data-close-canvas="id"    → closeCanvas(id) on success
//   data-reset="true"         → form.reset() on success
// Errors surface the FastAPI HTTPException `detail` as an error toast.
function swapRegion(selector, html) {
    try {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const fresh = doc.querySelector(selector);
        const current = document.querySelector(selector);
        if (fresh && current) {
            current.replaceWith(fresh);
            if (window.initDataTablesIn) window.initDataTablesIn(document.querySelector(selector));
            if (window.lucide) lucide.createIcons();
        }
    } catch (e) {
        console.error("swapRegion error:", e);
    }
}

document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-ajax]");
    if (!form) return;
    e.preventDefault();
    if (form.dataset.confirm && !await confirmDialog(form.dataset.confirm, {
        destructive: form.dataset.confirmDanger === "true",
    })) return;
    const submitBtn = form.querySelector('[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
        const res = await fetch(form.action, {
            method: (form.method || "post").toUpperCase(),
            body: new FormData(form),
            headers: { "X-Requested-With": "fetch" },
        });
        const html = await res.text();
        if (!res.ok) {
            let detail = "Thao tác thất bại.";
            try { detail = JSON.parse(html).detail || detail; } catch (_) { /* not JSON */ }
            toast(detail, "error");
            return;
        }
        toast(form.dataset.toast || "Đã hoàn tất thao tác.", "success");
        if (form.dataset.ajaxReload) swapRegion(form.dataset.ajaxReload, html);
        if (form.dataset.closeModal) closeModal(form.dataset.closeModal);
        if (form.dataset.closeCanvas) closeCanvas(form.dataset.closeCanvas);
        if (form.dataset.reset === "true") form.reset();
    } catch (err) {
        toast("Lỗi kết nối mạng.", "error");
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
});

// --- Overlay manager (modal + canvas + drawer) ------------------------------
// One shared stack so Escape closes the top-most overlay, body scroll locks
// exactly once, and focus is trapped + restored on close. `openModal(id)` /
// `closeModal(id)` / `openCanvas(id)` / `closeCanvas(id)` keep their historic
// signatures and also manage the `.open` class + `hidden` attribute that the
// templates' CSS (`.modal-backdrop.open`, `.canvas-backdrop.open`) relies on.

let overlayStack = [];
let bodyLockDepth = 0;

function bodyLockInc() {
    bodyLockDepth++;
    document.body.classList.add("n2e-body-lock");
}
function bodyLockDec() {
    bodyLockDepth = Math.max(0, bodyLockDepth - 1);
    if (bodyLockDepth === 0) document.body.classList.remove("n2e-body-lock");
}

function pushOverlay(el) {
    if (!overlayStack.includes(el)) overlayStack.push(el);
}
function popOverlay(el) {
    const i = overlayStack.indexOf(el);
    if (i !== -1) overlayStack.splice(i, 1);
}
function topOverlay() {
    return overlayStack[overlayStack.length - 1] || null;
}

const FOCUSABLE_SELECTOR =
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function restoreFocus(el) {
    const prev = el._n2eLastFocus;
    if (prev && prev.isConnected && typeof prev.focus === "function") prev.focus();
    delete el._n2eLastFocus;
}

function focusFirst(el) {
    const auto = el.querySelector("[data-autofocus], [autofocus]");
    if (auto) { auto.focus(); return; }
    const first = el.querySelector(FOCUSABLE_SELECTOR);
    if (first && !el.contains(document.activeElement)) first.focus();
}

function openOverlay(el, { canvas = false } = {}) {
    if (!el || overlayStack.includes(el)) return;
    if (el._n2eCloseTimer) {
        clearTimeout(el._n2eCloseTimer);
        delete el._n2eCloseTimer;
    }
    el._n2eLastFocus = document.activeElement;
    el.hidden = false;
    if (canvas) el.classList.remove("open");
    else el.classList.add("open");
    el.setAttribute("aria-hidden", "false");
    bodyLockInc();
    pushOverlay(el);
    requestAnimationFrame(() => {
        if (canvas) el.classList.add("open");
        focusFirst(el);
    });
}

function closeOverlay(el, { canvas = false } = {}) {
    if (!el) return;
    const wasOpen = overlayStack.includes(el);
    el.classList.remove("open");
    el.setAttribute("aria-hidden", "true");
    restoreFocus(el);
    popOverlay(el);
    if (wasOpen) bodyLockDec();
    if (canvas) {
        el._n2eCloseTimer = setTimeout(() => {
            el.hidden = true;
            delete el._n2eCloseTimer;
        }, 250);
    }
    else el.hidden = true;
}

function openModal(id) {
    const el = document.getElementById(id);
    if (el) openOverlay(el);
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) closeOverlay(el);
}

function openCanvas(id) {
    const el = document.getElementById(id);
    if (el) openOverlay(el, { canvas: true });
}
function closeCanvas(id) {
    const el = document.getElementById(id);
    if (el) closeOverlay(el, { canvas: true });
}

// Click a modal/canvas backdrop (not its content) to close it. Also close any
// open action-menu panel when clicking outside the menu.
document.addEventListener('click', (e) => {
    const modal = e.target.closest('.modal-backdrop');
    if (modal && e.target === modal) closeModal(modal.id);
    const canvas = e.target.closest('.canvas-backdrop');
    if (canvas && e.target === canvas) closeCanvas(canvas.id);
    if (!e.target.closest('.actions-menu')) closeActionMenus();
});

// --- Keyboard: Escape closes the top-most overlay, Tab is trapped inside it.
function trapTabFocus(overlay, e) {
    const focusables = Array.from(overlay.querySelectorAll(FOCUSABLE_SELECTOR));
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!overlay.contains(document.activeElement)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
        return;
    }
    if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const top = topOverlay();
        if (top) {
            if (top.classList.contains('n2e-drawer')) closeDrawer();
            else if (top.classList.contains('canvas-backdrop')) closeCanvas(top.id);
            else closeModal(top.id);
        } else {
            // Legacy elements opened without the overlay manager (e.g. the
            // confirm dialog) — close every visible overlay in one go.
            document.querySelectorAll('.modal-backdrop:not([hidden])').forEach((el) => closeModal(el.id));
            document.querySelectorAll('.canvas-backdrop.open').forEach((el) => closeCanvas(el.id));
        }
        closeActionMenus();
    } else if (e.key === 'Tab') {
        const top = topOverlay();
        if (top) trapTabFocus(top, e);
    }
});

// --- Mobile drawer (nav) ----------------------------------------------------
// Full-height slide-in nav below `md`. Breakpoint cleanup closes it whenever
// the viewport crosses up to desktop so no stale body-lock/focus state lingers.
function openDrawer() {
    const drawer = document.getElementById("n2e-drawer");
    if (!drawer) return;
    const btn = document.getElementById("drawer-open-btn");
    if (btn) btn.setAttribute("aria-expanded", "true");
    openOverlay(drawer, { canvas: true });
}
function closeDrawer() {
    const drawer = document.getElementById("n2e-drawer");
    if (!drawer) return;
    const btn = document.getElementById("drawer-open-btn");
    if (btn) btn.setAttribute("aria-expanded", "false");
    closeOverlay(drawer, { canvas: true });
}
document.addEventListener('click', (e) => {
    if (e.target.closest('[data-close-drawer]')) closeDrawer();
});
document.addEventListener('click', (e) => {
    if (e.target.closest('#drawer-open-btn')) {
        const drawer = document.getElementById("n2e-drawer");
        if (drawer && drawer.classList.contains("open")) closeDrawer();
        else openDrawer();
    }
});
(function initBreakpointCleanup() {
    const mq = window.matchMedia("(min-width: 768px)");
    const onChange = (e) => { if (e.matches) closeDrawer(); };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener(onChange);
})();

// --- Actions menu (mobile) --------------------------------------------------
// Shared delegated toggle for `.actions-menu` rows: clicking the "⋯" toggle
// opens that row's panel (and closes the others), clicking anywhere else
// closes every open panel. In-card expansion avoids clipping by the table's
// `overflow-x-auto` container (panels are absolutely positioned in-flow).
function closeActionMenus() {
    document.querySelectorAll('.actions-menu.open').forEach((m) => m.classList.remove('open'));
}
document.addEventListener('click', (e) => {
    const toggle = e.target.closest('.actions-menu-toggle');
    if (!toggle) return;
    const menu = toggle.closest('.actions-menu');
    if (!menu) return;
    const willOpen = !menu.classList.contains('open');
    closeActionMenus();
    menu.classList.toggle('open', willOpen);
    toggle.setAttribute('aria-expanded', String(willOpen));
    if (willOpen) menu.scrollIntoView({ block: 'nearest', inline: 'nearest' });
});

// --- Tab helpers ---
function switchTab(containerId, tabName) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const panels = container.querySelectorAll('.tab-content');
    const buttons = container.querySelectorAll('.tab-bar button');
    panels.forEach(p => p.classList.toggle('active', p.id === tabName));
    buttons.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
}

// Lucide icons sprite for toast (injected once)
if (!document.getElementById('lucide-sprite')) {
    const sprite = document.createElement('svg');
    sprite.id = 'lucide-sprite';
    sprite.style.display = 'none';
    sprite.innerHTML = `
        <symbol id="lucide-circle-x" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></symbol>
        <symbol id="lucide-circle-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="9 12 12 15 15 9"/></symbol>
        <symbol id="lucide-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></symbol>
        <symbol id="lucide-triangle-alert" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></symbol>
    `;
    document.body.appendChild(sprite);
}

// Lucide icon init for the initial render (was inline in base.html).
document.addEventListener('DOMContentLoaded', () => {
    if (window.lucide) lucide.createIcons();
});

// --- Soft reload helpers ----------------------------------------------------
// Fetch current page and swap <main> content without full navigation.
// Preserves scroll, JS state (scripts outside <main> don't re-execute).
async function softReload() {
    const res = await fetch(window.location.href);
    const text = await res.text();
    swapContent(text);
}
function swapContent(text) {
    const doc = new DOMParser().parseFromString(text, "text/html");
    const main = document.querySelector("main");
    const freshMain = doc.querySelector("main");
    if (main && freshMain) {
        main.innerHTML = freshMain.innerHTML;
    }
    if (window.initDataTablesIn) window.initDataTablesIn(document.querySelector("main"));
    if (window.lucide) lucide.createIcons();
}

function confirmDialog(message, { confirmLabel = "Xác nhận", destructive = false } = {}) {
    const dialog = document.getElementById("confirm-dialog");
    const messageEl = document.getElementById("confirm-dialog-message");
    const cancelBtn = document.getElementById("confirm-dialog-cancel");
    const confirmBtn = document.getElementById("confirm-dialog-confirm");
    if (!dialog || !messageEl || !cancelBtn || !confirmBtn) return Promise.resolve(false);

    messageEl.textContent = String(message);
    confirmBtn.textContent = confirmLabel;
    confirmBtn.classList.toggle("confirm-destructive", destructive);
    dialog.hidden = false;
    dialog.classList.add("open");
    bodyLockInc();
    cancelBtn.focus();

    return new Promise((resolve) => {
        let settled = false;
        const finish = (result) => {
            if (settled) return;
            settled = true;
            dialog.hidden = true;
            dialog.classList.remove("open");
            bodyLockDec();
            cancelBtn.removeEventListener("click", cancel);
            confirmBtn.removeEventListener("click", confirm);
            dialog.removeEventListener("click", backdrop);
            document.removeEventListener("keydown", escape);
            resolve(result);
        };
        const cancel = () => finish(false);
        const confirm = () => finish(true);
        const backdrop = (event) => { if (event.target === dialog) finish(false); };
        const escape = (event) => { if (event.key === "Escape") finish(false); };
        cancelBtn.addEventListener("click", cancel);
        confirmBtn.addEventListener("click", confirm);
        dialog.addEventListener("click", backdrop);
        document.addEventListener("keydown", escape);
    });
}

function showPopupMessage(popupDocument, message, kind = "info") {
    let region = popupDocument.getElementById("popup-toast-region");
    if (!region) {
        region = popupDocument.createElement("div");
        region.id = "popup-toast-region";
        region.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;display:flex;max-width:min(28rem,calc(100vw - 32px));flex-direction:column;gap:8px;pointer-events:none";
        popupDocument.body.appendChild(region);
    }
    const el = popupDocument.createElement("div");
    const colors = kind === "error"
        ? ["#fef2f2", "#991b1b", "#fecaca"]
        : kind === "success"
        ? ["#f0fdf4", "#166534", "#bbf7d0"]
        : kind === "warning"
        ? ["#fffbeb", "#92400e", "#fde68a"]
        : ["#eff6ff", "#1e40af", "#bfdbfe"];
    el.style.cssText = `box-sizing:border-box;padding:12px 16px;border:1px solid ${colors[2]};border-radius:8px;background:${colors[0]};color:${colors[1]};font:14px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.18);opacity:0;transform:translateY(8px);transition:opacity .2s ease,transform .2s ease`;
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.textContent = String(message);
    region.appendChild(el);
    requestAnimationFrame(() => {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
    });
    setTimeout(() => {
        el.style.opacity = "0";
        el.style.transform = "translateY(8px)";
        setTimeout(() => el.remove(), 200);
    }, 4000);
}
