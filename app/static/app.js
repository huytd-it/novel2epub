// Shell dùng chung mọi trang: theme toggle (persist localStorage), toast
// helper, và queue indicator poll /api/queue (xem spec ui-design-system).

function toast(message, kind) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " toast-" + kind : "");
    el.textContent = message;
    region.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
        el.classList.remove("show");
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

(function initTheme() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
        const root = document.documentElement;
        const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
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
            if (indicator) indicator.classList.toggle("active", total > 0);
        } catch (e) {
            // Im lặng: trang chưa có /api/queue (vd test môi trường cũ) không nên báo lỗi ồn ào.
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
