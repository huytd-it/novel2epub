import sys
sys.path.insert(0, '.')
from novel2epub.config import load_config
from novel2epub.storage import Storage
from novel2epub.toc import chapter_rows, apply_chapter_query

cfg = load_config('novel2epub.yaml', 'thanh-son')
storage = Storage(cfg.output.data_dir, cfg.novel.slug)
manifest = storage.load_manifest()

rows = apply_chapter_query(chapter_rows(manifest.chapters, storage))

# Check for unusually long values
for r in rows:
    if len(r.url) > 500:
        print(f'LONG URL: ch#{r.index} url={r.url[:100]}... (len={len(r.url)})')
    if len(r.visible_title) > 200:
        print(f'LONG TITLE: ch#{r.index} title={r.visible_title[:100]}... (len={len(r.visible_title)})')
    if len(r.last_action_status) > 500:
        print(f'LONG STATUS: ch#{r.index} status={r.last_action_status[:100]}... (len={len(r.last_action_status)})')

print(f'Max url length: {max(len(r.url) for r in rows)}')
print(f'Max title length: {max(len(r.visible_title) for r in rows)}')
print(f'Max status length: {max(len(r.last_action_status) or "" for r in rows)}')

# Check for any rows with word_count > 100000
for r in rows:
    if r.word_count > 100000:
        print(f'LARGE WORD COUNT: ch#{r.index} word_count={r.word_count}')

print("Inspection complete")
