import json, sys
sys.path.insert(0, '.')
from novel2epub.config import load_config
from novel2epub.storage import Storage
from novel2epub.toc import chapter_rows, apply_chapter_query

cfg = load_config('novel2epub.yaml', 'thanh-son')
storage = Storage(cfg.output.data_dir, cfg.novel.slug)
manifest = storage.load_manifest()
print(f'Manifest loaded: {manifest is not None}')
print(f'Chapters in manifest: {len(manifest.chapters)}')
from dataclasses import asdict
rows = apply_chapter_query(chapter_rows(manifest.chapters, storage))
print(f'ChapterRows: {len(rows)}')
j = [asdict(r) for r in rows]
print(f'JSON items: {len(j)}')
# Test serialization
json_str = json.dumps(j, ensure_ascii=False)
print(f'JSON length: {len(json_str)}')
print(f'Valid JSON: True')
# Check first item
first = j[0]
print(f'First item type: {type(first)}')
for key, val in first.items():
    print(f'  {key}: {type(val).__name__} = {str(val)[:50]}')
