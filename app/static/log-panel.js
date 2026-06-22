// Tiện ích cho khung log: search lọc dòng + copy toàn bộ log vào clipboard.
function initLogPanel(preId) {
    const pre = document.getElementById(preId);
    if (!pre) return { setLines() {} };

    const wrap = document.createElement("div");
    wrap.className = "log-wrap";

    const toolbar = document.createElement("div");
    toolbar.className = "log-toolbar";
    toolbar.innerHTML = `
        <input type="search" class="log-search" placeholder="Tìm trong log...">
        <span class="log-count"></span>
        <button type="button" class="log-copy">📋 Copy log</button>
    `;

    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(toolbar);
    wrap.appendChild(pre);

    const searchEl = toolbar.querySelector(".log-search");
    const countEl = toolbar.querySelector(".log-count");
    const copyBtn = toolbar.querySelector(".log-copy");

    let rawLines = [];

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function render() {
        const q = searchEl.value.trim();
        if (!q) {
            pre.textContent = rawLines.join("\n");
            countEl.textContent = rawLines.length ? `${rawLines.length} dòng` : "";
        } else {
            const ql = q.toLowerCase();
            const matched = rawLines.filter((line) => line.toLowerCase().includes(ql));
            const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
            pre.innerHTML = matched
                .map((line) => escapeHtml(line).replace(re, (m) => `<mark class="log-hit">${m}</mark>`))
                .join("\n");
            countEl.textContent = `${matched.length}/${rawLines.length} dòng khớp`;
        }
        pre.scrollTop = pre.scrollHeight;
    }

    searchEl.addEventListener("input", render);

    copyBtn.addEventListener("click", async () => {
        const text = rawLines.join("\n");
        try {
            await navigator.clipboard.writeText(text);
        } catch (e) {
            // Fallback cho môi trường không hỗ trợ Clipboard API (vd http không có secure context).
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
        const old = copyBtn.textContent;
        copyBtn.textContent = "✅ Đã copy";
        setTimeout(() => { copyBtn.textContent = old; }, 1500);
    });

    return {
        setLines(lines) {
            rawLines = lines || [];
            render();
        },
    };
}
