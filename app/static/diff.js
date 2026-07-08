// Diff thuần dùng chung cho editor (chapter.html: diff bản nháp AI) và
// reader (chế độ so sánh MT vs Biên tập). Expose qua window.n2eDiff.
(function () {
    // LCS diff tổng quát trên mảng token, trả [left, right] dạng [kind, token]
    // với kind: "eq" | "del" (chỉ left) | "ins" (chỉ right).
    function lcsDiff(a, b) {
        const n = a.length, m = b.length;
        const lcs = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
        for (let i = n - 1; i >= 0; i--)
            for (let j = m - 1; j >= 0; j--)
                lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
        const left = [], right = [];
        let i = 0, j = 0;
        while (i < n && j < m) {
            if (a[i] === b[j]) { left.push(["eq", a[i]]); right.push(["eq", b[j]]); i++; j++; }
            else if (lcs[i + 1][j] >= lcs[i][j + 1]) { left.push(["del", a[i]]); i++; }
            else { right.push(["ins", b[j]]); j++; }
        }
        while (i < n) left.push(["del", a[i++]]);
        while (j < m) right.push(["ins", b[j++]]);
        return [left, right];
    }

    function lineDiff(aText, bText) {
        return lcsDiff(aText.split("\n"), bText.split("\n"));
    }

    // Diff theo từ trong 1 đoạn — tách theo khoảng trắng nhưng GIỮ khoảng
    // trắng làm token riêng để ghép lại không mất định dạng.
    function wordDiff(aText, bText) {
        const tokenize = (s) => s.split(/(\s+)/).filter((t) => t !== "");
        return lcsDiff(tokenize(aText), tokenize(bText));
    }

    function escapeHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function renderDiffCol(el, rows) {
        el.innerHTML = rows.map(([kind, line]) =>
            `<div class="diff-line ${kind}">${escapeHtml(line) || "&nbsp;"}</div>`
        ).join("");
    }

    // Render 1 đoạn với các token del/ins bọc <del>/<ins> — build bằng DOM
    // (textContent) nên an toàn với mọi nội dung.
    function renderWordDiffInto(el, rows) {
        el.textContent = "";
        for (const [kind, token] of rows) {
            if (kind === "eq") {
                el.appendChild(document.createTextNode(token));
            } else {
                const wrap = document.createElement(kind === "del" ? "del" : "ins");
                wrap.textContent = token;
                el.appendChild(wrap);
            }
        }
    }

    window.n2eDiff = { lineDiff, wordDiff, renderDiffCol, renderWordDiffInto };
})();
