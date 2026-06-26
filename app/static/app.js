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
