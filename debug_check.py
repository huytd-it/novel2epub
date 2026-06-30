import json, sys, urllib.request
sys.path.insert(0, '.')
from novel2epub.config import load_config
from novel2epub.storage import Storage
from novel2epub.toc import chapter_rows, apply_chapter_query
from dataclasses import asdict

cfg = load_config('novel2epub.yaml', 'thanh-son')
storage = Storage(cfg.output.data_dir, cfg.novel.slug)
manifest = storage.load_manifest()
print(f'Manifest loaded: {manifest is not None}')
print(f'Chapters in manifest: {len(manifest.chapters)}')

rows = apply_chapter_query(chapter_rows(manifest.chapters, storage))
print(f'ChapterRows: {len(rows)}')

# Check for None/empty values
for i, r in enumerate(rows):
    if r.url is None or r.url == '':
        print(f'Chapter {r.index}: url is empty/None')
    if r.visible_title is None:
        print(f'Chapter {r.index}: visible_title is None')
    if r.missing_fields is None:
        print(f'Chapter {r.index}: missing_fields is None')
    if r.last_action_status is None:
        print(f'Chapter {r.index}: last_action_status is None')

# Serialize and check for issues
j = [asdict(r) for r in rows]
json_str = json.dumps(j, ensure_ascii=True)
print(f'JSON length: {len(json_str)}')
print('JSON is valid: True')

# Check for values that could cause JS issues
for item in j:
    for key in ('visible_title', 'url', 'last_action_status'):
        if item.get(key) is None:
            print(f'Chapter {item["index"]}: {key} is None in JSON')
print('No None values found in critical fields')

# Print first item (without unicode in console)
import sys
first = j[0]
print(f'First chapter: index={first["index"]}, has_raw={first["has_raw"]}, has_translated={first["has_translated"]}')
