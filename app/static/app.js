// Shell dùng chung mọi trang: theme toggle (persist localStorage), toast
// helper, queue indicator poll /api/queue, modal/canvas/tab helpers.

function toast(message, kind) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const el = document.createElement("div");
    const base = "flex items-center gap-2 rounded-lg border bg-surface-light dark:bg-surface-dark text-fg-light dark:text-fg-dark px-3 py-2 text-sm shadow-card dark:shadow-card-dark transition-all duration-300 ease-out";
    const variant = kind === "error"
        ? " border-red-500"
        : kind === "success"
        ? " border-green-500"
        : " border-border-light dark:border-border-dark";
    el.className = base + variant + " opacity-0 translate-y-2";
    const iconName = kind === "error" ? "circle-x" : kind === "success" ? "circle-check" : "info";
    el.innerHTML = `<i data-lucide="${iconName}" class="w-4 h-4 flex-shrink-0"></i><span>${message}</span>`;
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
    });
})();

(function initQueueIndicator() {
    const countEl = document.getElementById("queue-count");
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
                indicator.classList.toggle("active", active);
                // Tailwind: amber pill khi active
                indicator.classList.toggle("border-amber-500", active);
                indicator.classList.toggle("bg-amber-100", active);
                indicator.classList.toggle("text-amber-800", active);
                indicator.classList.toggle("dark:bg-amber-900/30", active);
                indicator.classList.toggle("dark:text-amber-200", active);
            }
        } catch (e) {
            // Im lặng: trang chưa có /api/queue không nên báo lỗi ồn ào.
        }
    }

    poll();
    setInterval(poll, 3000);
})();

// --- Modal helpers ---
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.hidden = false;
}
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.hidden = true;
}
document.addEventListener('click', (e) => {
    const backdrop = e.target.closest('.modal-backdrop');
    if (backdrop && e.target === backdrop) backdrop.hidden = true;
});

// --- Canvas (slide-in panel) helpers ---
function openCanvas(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.remove('open');
        el.hidden = false;
        requestAnimationFrame(() => el.classList.add('open'));
    }
}
function closeCanvas(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.remove('open');
        setTimeout(() => el.hidden = true, 250);
    }
}
document.addEventListener('click', (e) => {
    const backdrop = e.target.closest('.canvas-backdrop');
    if (backdrop && e.target === backdrop) {
        const id = backdrop.id;
        closeCanvas(id);
    }
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.canvas-backdrop.open').forEach(el => {
            closeCanvas(el.id);
        });
        document.querySelectorAll('.modal-backdrop:not([hidden])').forEach(el => {
            el.hidden = true;
        });
    }
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
