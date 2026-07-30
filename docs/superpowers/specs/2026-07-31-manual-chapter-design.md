# Manual Chapter Design

## Goal

Allow a user to add one chapter TOC entry manually from the ebook workspace when the source TOC is incomplete or a chapter was omitted. The user chooses the insertion position and supplies a title and source URL. Existing crawl, translation, editing, and build actions continue to handle chapter content.

## Scope

The feature adds only chapter metadata. It does not accept pasted raw or translated content, start a crawl automatically, or change the existing TOC fetch behavior.

## User Interface

Add a `Thêm chương thủ công` button beside `Lấy toàn bộ danh mục` in `app/templates/ebook.html`. The button opens a small modal with:

- `Vị trí`: required integer, defaulting to `N + 1`, with valid range `1..N+1`.
- `Tiêu đề`: required text.
- `URL nguồn`: required URL.
- `Hủy` and `Thêm chương` actions.

The modal uses the existing modal and button styles. Its form submits with a normal POST so it remains usable without custom fetch logic. On success the route redirects to the ebook workspace, where the existing client-side table renders the inserted chapter. The existing sort and filter controls determine where it appears visually.

## Route

Add `POST /ebooks/{slug}/chapters/manual` to the chapter routes. It resolves the ebook configuration, normalizes whitespace around the title and URL, and validates:

- A manifest exists for the ebook.
- The title is not empty.
- The URL is not empty.
- The insertion index is between `1` and `N + 1`, inclusive.
- No chapter in the ebook already uses the URL.

Invalid requests return HTTP 400 and do not modify chapter rows. A successful request redirects to `/ebooks/{slug}` with HTTP 303.

## Storage Operation

Add a dedicated `Storage.insert_chapter(chapter)` operation. The operation owns validation that depends on current persisted state and performs insertion atomically.

Within one SQLite transaction it:

1. Confirms the ebook row exists.
2. Reads the current chapter count and validates the requested index.
3. Rejects a duplicate URL for the ebook.
4. Shifts every complete chapter row at or after the requested index upward by one, processing indexes from highest to lowest to avoid primary-key collisions.
5. Inserts the new row at the requested index.

The shift updates the primary key of each existing row rather than reconstructing rows from `Manifest`. Consequently it preserves URL, titles, flags, raw text, translated text, MT snapshot, metadata JSON, timestamps, and any future columns stored on the chapter row.

The inserted `Chapter` has the submitted title in both `title` and `title_zh`, the submitted URL, and default values for all other fields. Setting both title fields preserves the original manually entered source title if the visible title is later translated or edited.

The method raises `ValueError` for invalid position or duplicate URL. The route converts this expected validation failure to HTTP 400. Unexpected database errors propagate and SQLite rolls the transaction back.

## Concurrency And Integrity

Index validation, duplicate detection, shifting, and insertion occur in the same write transaction. No partial shift is committed if validation or insertion fails. The implementation must not use `save_manifest` or `step_reorder`, because those APIs reconstruct chapter metadata by index and are not an appropriate boundary for moving persisted content rows.

## Testing

Storage tests cover:

- Inserting the first chapter into an ebook with an empty manifest.
- Appending at `N + 1`.
- Inserting in the middle and preserving all fields and content of shifted rows.
- Rejecting positions below `1` and above `N + 1` without modification.
- Rejecting duplicate URLs without modification.

Route and template tests cover:

- Required title, URL, and index validation.
- Successful insertion and HTTP 303 redirect.
- Duplicate URL and invalid index returning HTTP 400.
- Presence of the manual-add button, modal fields, and form action in `ebook.html`.

## Non-Goals

- Pasting raw or translated chapter content.
- Automatically crawling the newly added chapter.
- Bulk manual insertion.
- Allowing duplicate source URLs.
- Reordering chapters through this form after insertion.
