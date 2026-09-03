import pathlib, tempfile
from novel2epub.db import get_connection, init_schema
from novel2epub.config import CrawlConfig
from novel2epub.crawler import fetch_chapter_paginated
from novel2epub.storage import Storage, Chapter, Manifest
from novel2epub.toc import chapter_rows, apply_chapter_query

tmp = tempfile.mkdtemp()
print("tmp", tmp)
dbp = pathlib.Path(tmp) / "novel2epub.db"
c = get_connection(str(dbp))
init_schema(c)
print("fresh schema_version", c.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()[0])
cols = [r[1] for r in c.execute("PRAGMA table_info(chapters)").fetchall()]
print("chapters has crawl_pages", "crawl_pages" in cols)
cols2 = [r[1] for r in c.execute("PRAGMA table_info(chapter_ui_state)").fetchall()]
print("ui_state has crawl_pages", "crawl_pages" in cols2)

# seed ebook
c.execute("INSERT INTO ebooks(slug) VALUES ('demo')")
c.commit()
st = Storage(tmp, "demo")
ch1 = Chapter(index=1, url="https://ex.com/ch1.html", title="Chuong 1")
ch2 = Chapter(index=2, url="https://ex.com/ch2.html", title="Chuong 2")
st.save_manifest(Manifest(slug="demo", chapters=[ch1, ch2]))
st.write_raw(ch1, "hello raw 1", crawl_pages=4)
st.write_raw(ch2, "hello raw 2", crawl_pages=1)
print("crawl_pages ch1", st.crawl_pages(ch1), "ch2", st.crawl_pages(ch2))
mp = st.bulk_chapter_stats()
print("bulk", mp)
rows = chapter_rows([ch1, ch2], st, stats_map=mp)
for r in rows:
    print(f"row {r.index} pages={r.crawl_pages} raw={r.has_raw}")
s = apply_chapter_query(rows, sort="pages", direction="desc")
print("sorted desc pages", [(r.index, r.crawl_pages) for r in s])
s2 = apply_chapter_query(rows, sort="pages", direction="asc")
print("sorted asc pages", [(r.index, r.crawl_pages) for r in s2])
st.write_raw(ch1, "hello raw 1 v2")
print("after replace without pages, ch1 pages", st.crawl_pages(ch1))
st.write_raw(ch2, "", crawl_pages=0)
print("empty ch2 pages", st.crawl_pages(ch2))
c.close()

cfg = CrawlConfig(toc_url="https://ex.com/toc", chapter_link_pattern="ch", max_pages_per_chapter=10, next_page_selector="a.next")
ch = Chapter(index=1, url="https://ex.com/c1.html")
pages_data = {
    "https://ex.com/c1.html": ("Title\nBody p1", "https://ex.com/c1_2.html"),
    "https://ex.com/c1_2.html": ("Title\nBody p2", "https://ex.com/c1_3.html"),
    "https://ex.com/c1_3.html": ("Title\nBody p3", None),
}
def fp(url):
    class P: pass
    p = P()
    txt, nxt = pages_data[url]
    p._txt = txt
    p._nxt = nxt
    return p
def et(p): return p._txt
def npu(cur, pg): return pg._nxt

txt, n = fetch_chapter_paginated(cfg, ch, fetch_page=fp, extract_text=et, next_page_url=npu)
print(f"paginated pages={n} has Body p3={('Body p3' in txt)}")
print("ALL SMOKE OK")
