## ADDED Requirements

### Requirement: MoxhiMTTranslator dùng rule-based normalization cho chapter titles

Hệ thống SHALL thêm method `_normalize_title(text: str) -> str | None` trong `MoxhiMTTranslator` để xử lý các pattern chapter title phổ biến bằng rule (regex), tránh đưa title ngắn vào NMT model gây hallucinate.

Các pattern SHALL được xử lý:
- `第(\d+)章` → `Chương \1`
- `第([一二三四五六七八九十百千]+)章` → chuyển số Hán tự sang số Ả Rập → `Chương N`
- `序章` → `Mở đầu`
- `楔子` → `Mở đầu`
- `尾声` / `后记` → `Kết thúc`
- `第(\d+)节` → `Mục \1`
- `番外(\d*)` → `Ngoại truyện\1`

Khi không match pattern nào, trả về `None` để fallback sang NMT.

#### Scenario: Normalize "第1章"
- **WHEN** `_normalize_title("第1章")` được gọi
- **THEN** trả về `"Chương 1"`

#### Scenario: Normalize "序章"
- **WHEN** `_normalize_title("序章")` được gọi
- **THEN** trả về `"Mở đầu"`

#### Scenario: Title không match pattern
- **WHEN** `_normalize_title("赤心巡天")` được gọi
- **THEN** trả về `None` (fallback sang NMT)

### Requirement: translate_title gọi _normalize_title trước

`MoxhiMTTranslator.translate_title()` SHALL gọi `_normalize_title()` trước. Nếu trả về string khác None, dùng luôn kết quả đó (không gọi NMT). Nếu None, fallback sang `_translate_line()`.

#### Scenario: translate_title cho "第1章"
- **WHEN** `translate_title("第1章")` được gọi
- **THEN** `_normalize_title("第1章")` trả `"Chương 1"`
- **THEN** trả về `("Chương 1", "")` — không gọi `_translate_line`

### Requirement: MoxhiMTTranslator không dùng prompt template khi dịch

Hệ thống SHALL đảm bảo `MoxhiMTTranslator.translate()` không đọc, xây dựng, hoặc sử dụng bất kỳ prompt template nào. Toàn bộ luồng dịch SHALL là:
1. Text gốc → SentencePiece tokenize
2. Token IDs → CTranslate2 model inference
3. Output token IDs → SentencePiece detokenize
4. Hậu xử lý: `_apply_glossary()` (string-replace)

Không có `_build_prompt()`, không có system message, không có template format.

#### Scenario: translate() không gọi _build_prompt
- **WHEN** `MoxhiMTTranslator.translate(text)` được gọi
- **THEN** không có method `_build_prompt` nào được gọi
- **THEN** text gốc được đưa thẳng vào SentencePiece tokenizer

#### Scenario: translate_title() fallback về translate thuần
- **WHEN** `MoxhiMTTranslator.translate_title(text, kind)` được gọi
- **THEN** nó SHALL gọi `self.translate(text)` (không prompt)
- **THEN** trả về `(translated_text, "")` — note rỗng vì không có LLM để giải thích

### Requirement: Hành vi translate_title được document

Trong code của `MoxhiMTTranslator`, comment hoặc docstring SHALL xác nhận rằng `translate_title` dùng `self.translate()` — tức là dịch thuần không prompt — khác với `OpenAITranslator` dùng `_build_title_prompt()`.

#### Scenario: translate_title trong moxhimt không dùng prompt
- **WHEN** kiểm tra code `MoxhiMTTranslator.translate_title`
- **THEN** method đó SHALL chỉ gọi `self.translate(text)` và trả `(result, "")`
