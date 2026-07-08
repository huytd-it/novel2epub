// Reusable, dependency-free "data table" enhancer for server-rendered tables.
// Adds a search box, click-to-sort headers, and auto per-column dropdown
// filters — matching the app's vanilla/Tailwind house style (no jQuery), the
// same pattern queue.html / glossary.html already use, but driven by markup so
// any server-rendered <table> can opt in.
//
// Markup contract (see sources.html / storage.html / automation.html):
//   <table data-dt data-dt-placeholder="Tìm…">
//     <thead><tr>
//       <th data-dt-sort>Tên</th>                    ← sortable (click to toggle)
//       <th data-dt-sort data-dt-filter>Engine</th>  ← sortable + dropdown filter
//       <th>Thao tác</th>                            ← plain column
//     </tr></thead>
//     <tbody>…server-rendered rows…</tbody>
//   </table>
// A toolbar (search + column filters + result count) is injected above the
// table. Everything stays in the DOM: rows are hidden/reordered in place, so no
// rendering logic is duplicated in JS (progressive enhancement).

(function () {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const lower = (s) => norm(s).toLowerCase();

    function cellText(row, i) {
        const c = row.cells[i];
        return c ? norm(c.textContent) : "";
    }

    // "Empty state" rows (a single cell spanning every column) are not data.
    function isDataRow(row) {
        return !(row.cells.length === 1 && row.cells[0].colSpan > 1);
    }

    const NUMERIC_RE = /^[\s\d.,\-]*(mb|kb|gb|b|%)?\s*$/i;

    function initDataTable(table) {
        if (table.__dt) return; // idempotent
        table.__dt = true;

        const thead = table.tHead;
        const tbody = table.tBodies[0];
        if (!thead || !tbody || !thead.rows.length) return;
        const headers = Array.from(thead.rows[0].cells);

        // ── Toolbar (search + filters + count) ─────────────────────────────
        const wrapper = table.closest(".overflow-x-auto") || table;
        const toolbar = document.createElement("div");
        toolbar.className = "flex flex-wrap items-center gap-2 mb-2";

        const search = document.createElement("input");
        search.type = "search";
        search.placeholder = table.dataset.dtPlaceholder || "Tìm kiếm…";
        search.className =
            "rounded-md border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-link-light/40";
        toolbar.appendChild(search);

        const filters = []; // {col, select}
        headers.forEach((th, i) => {
            if (!th.hasAttribute("data-dt-filter")) return;
            const label = norm(th.textContent) || "Cột " + (i + 1);
            const values = new Set();
            Array.from(tbody.rows).filter(isDataRow).forEach((r) => {
                const v = cellText(r, i);
                if (v) values.add(v);
            });
            const sel = document.createElement("select");
            sel.className =
                "rounded-md border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark px-2 py-1.5 text-sm";
            sel.innerHTML =
                `<option value="">${label}: tất cả</option>` +
                Array.from(values)
                    .sort((a, b) => a.localeCompare(b, "vi"))
                    .map((v) => `<option value="${v.replace(/"/g, "&quot;")}">${v}</option>`)
                    .join("");
            sel.addEventListener("change", render);
            toolbar.appendChild(sel);
            filters.push({ col: i, select: sel });
        });

        const count = document.createElement("span");
        count.className = "text-sm text-muted-light dark:text-muted-dark ml-auto";
        toolbar.appendChild(count);

        wrapper.parentNode.insertBefore(toolbar, wrapper);

        // ── Sorting ────────────────────────────────────────────────────────
        let sortCol = -1;
        let sortDir = 1;
        headers.forEach((th, i) => {
            if (!th.hasAttribute("data-dt-sort")) return;
            th.classList.add("cursor-pointer", "select-none");
            const ind = document.createElement("span");
            ind.className = "dt-ind text-muted-light dark:text-muted-dark ml-1 opacity-40";
            ind.textContent = "⇅";
            th.appendChild(ind);
            th.addEventListener("click", () => {
                if (sortCol === i) sortDir = -sortDir;
                else {
                    sortCol = i;
                    sortDir = 1;
                }
                headers.forEach((h) => {
                    const s = h.querySelector(".dt-ind");
                    if (s) { s.textContent = "⇅"; s.classList.add("opacity-40"); s.classList.remove("opacity-100"); }
                });
                ind.textContent = sortDir > 0 ? "▲" : "▼";
                ind.classList.remove("opacity-40");
                ind.classList.add("opacity-100");
                render();
            });
        });

        function compare(a, b, i) {
            const av = cellText(a, i);
            const bv = cellText(b, i);
            const an = parseFloat(av.replace(/[^0-9.\-]/g, ""));
            const bn = parseFloat(bv.replace(/[^0-9.\-]/g, ""));
            const numeric =
                av !== "" && bv !== "" && !isNaN(an) && !isNaN(bn) &&
                NUMERIC_RE.test(av) && NUMERIC_RE.test(bv);
            if (numeric) return an - bn;
            return av.localeCompare(bv, "vi");
        }

        function render() {
            const q = lower(search.value);
            const rows = Array.from(tbody.rows).filter(isDataRow);
            let shown = 0;
            rows.forEach((r) => {
                let ok = !q || lower(r.textContent).includes(q);
                if (ok) {
                    for (const f of filters) {
                        if (f.select.value && cellText(r, f.col) !== f.select.value) {
                            ok = false;
                            break;
                        }
                    }
                }
                r.style.display = ok ? "" : "none";
                if (ok) shown++;
            });
            if (sortCol >= 0) {
                rows.slice()
                    .sort((a, b) => compare(a, b, sortCol) * sortDir)
                    .forEach((r) => tbody.appendChild(r));
            }
            count.textContent =
                shown === rows.length ? `${rows.length} mục` : `${shown} / ${rows.length} mục`;

            let empty = tbody.querySelector(".dt-empty");
            if (shown === 0 && rows.length > 0) {
                if (!empty) {
                    empty = document.createElement("tr");
                    empty.className = "dt-empty";
                    empty.innerHTML =
                        `<td colspan="${headers.length}" class="text-center text-muted-light dark:text-muted-dark py-6 text-sm">Không có mục nào khớp.</td>`;
                    tbody.appendChild(empty);
                }
                empty.style.display = "";
            } else if (empty) {
                empty.style.display = "none";
            }
        }

        search.addEventListener("input", render);
        render();
    }

    function initAll(root) {
        (root || document).querySelectorAll("table[data-dt]").forEach(initDataTable);
    }

    window.initDataTable = initDataTable;
    window.initDataTablesIn = initAll;
    document.addEventListener("DOMContentLoaded", () => initAll(document));
})();
