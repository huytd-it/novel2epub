"""Đọc và xác thực file cấu hình YAML."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CrawlConfig:
    toc_url: str
    # engine: http (requests+BS4) | crawl4ai (browser, JS)
    engine: str = "http"
    chapter_link_pattern: str = r".*"
    max_chapters: int = 0
    strip_patterns: list[str] = field(default_factory=list)
    delay_seconds: float = 1.0

    # ----- multi-page chapter (pagination) -----
    # CSS selector cho link "trang tiếp" trong chương (vd "a#pager_next",
    # "a.next"). Khi tìm thấy, crawler tải nội dung trang đó rồi nối vào
    # chương hiện tại. Để trống = không paginate.
    next_page_selector: str = ""
    # Regex fallback cho site không có link "trang tiếp" rõ ràng (vd JS
    # navigation). Phải chứa đúng 1 capturing group; group sẽ được thay
    # bằng hậu tố tăng dần ("_2", "_3", ...) để dò URL trang kế tiếp.
    next_page_url_pattern: str = ""
    # Số trang tối đa cho 1 chương (an toàn, tránh loop vô hạn).
    max_pages_per_chapter: int = 10

    def __post_init__(self) -> None:
        if self.next_page_url_pattern:
            try:
                pat = re.compile(self.next_page_url_pattern)
            except re.error as e:
                raise ValueError(
                    f"crawl.next_page_url_pattern không phải regex hợp lệ: {e}"
                ) from e
            unnamed_groups = pat.groups
            named_groups = len(pat.groupindex)
            total = unnamed_groups + named_groups
            if total != 1:
                raise ValueError(
                    "crawl.next_page_url_pattern phải chứa đúng 1 capturing "
                    f"group, hiện có {total}."
                )

    # CSS selector vùng chứa nội dung chương (vd "#content", ".read-content").
    # Dùng cho cả 2 engine: engine "http" dùng để bóc text trực tiếp; engine
    # "crawl4ai" dùng làm css_selector cho CrawlerRunConfig (giới hạn vùng
    # crawl4ai render Markdown).
    content_selector: str = ""

    # ----- chỉ dùng cho engine = "http" -----
    # CSS selector vùng chứa danh sách link chương ở trang mục lục (tùy chọn,
    # giúp loại bỏ link rác ở header/footer). Vd "#list", ".listmain".
    # KHÔNG áp dụng cho engine "crawl4ai" (fetch_toc của engine đó quét toàn
    # trang theo chapter_link_pattern, không scope theo toc_selector).
    toc_selector: str = ""
    # CSS selector tiêu đề chương (tùy chọn). Vd "h1".
    chapter_title_selector: str = ""
    # ----- selector metadata truyện ở trang mục lục/giới thiệu, chỉ dùng cho
    # engine = "http" (tùy chọn) -----
    # Để trống thì crawler tự lấy từ thẻ OG/meta chuẩn (og:title, og:novel:author,
    # og:description, og:image...). Đặt selector khi trang không có thẻ OG.
    # KHÔNG áp dụng cho engine "crawl4ai" (engine đó chỉ đọc og:meta, bỏ qua
    # các selector này).
    title_selector: str = ""
    author_selector: str = ""
    desc_selector: str = ""
    cover_selector: str = ""
    # Bảng mã trang. Để trống = tự đoán (apparent_encoding). Vd "gbk", "utf-8".
    encoding: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # ----- chỉ dùng cho engine = "crawl4ai" -----
    # Chạy trình duyệt ẩn (headless). Đặt False để debug bằng cửa sổ thật.
    headless: bool = True
    # JS để chờ/điều khiển trang (vd cuộn lazy-load). Tùy chọn.
    js_code: str = ""
    # Vượt bot detection tốt hơn (Crawl4AI undetected/magic mode).
    magic: bool = True

    # ----- AI fallback crawl (experimental, cần translate.preset: go) -----
    # Khi selector không trích được nội dung, gửi HTML thô cho AI CLI
    # (opencode run) để trích xuất chương bằng LLM.
    ai_fallback: bool = False
    # Giới hạn ký tự HTML gửi cho AI (tránh vượt context window).
    ai_fallback_max_html: int = 32000
    # CLI config cho AI fallback (do pipeline gán khi tạo crawler).
    _cli_fallback: Any = None  # CliTranslatorConfig | None


@dataclass
class GlossaryFilesConfig:
    names: str = ""
    vietphrase: str = ""


@dataclass
class TranslationStyleConfig:
    tone: str = "mượt, tự nhiên, có chất cổ trang"
    pronoun_policy: str = "contextual"
    keep_paragraphs: bool = True
    title_mode: str = "creative"
    han_viet_level: str = "balanced"


@dataclass
class TranslationRetryConfig:
    attempts: int = 1
    delay_seconds: float = 0.0


@dataclass
class TranslationChunkConfig:
    max_chars: int = 0
    overlap_paragraphs: int = 0


DEFAULT_PROMPT = """Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt, theo phong cách edit mượt mà mà độc giả Việt quen thuộc.

Nguyên tắc bắt buộc:
1. Dịch sang tiếng Việt tự nhiên, đúng ngữ pháp Việt: đảo trật tự từ cho thuận, đưa trạng ngữ lên đầu câu khi hợp lý, câu phải đủ chủ-vị.
2. Ngôi xưng phải theo quan hệ và ngữ cảnh, KHÔNG bê nguyên ta/ngươi. Chọn phù hợp giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/bà ấy/ngài/người/con/cháu...
3. Tên riêng, công pháp, địa danh, chiêu thức: giữ theo lối Hán Việt quen thuộc, viết hoa và nhất quán.
4. Hạn chế lạm dụng từ Hán Việt khó hiểu; ưu tiên thuần Việt nếu rõ nghĩa hơn, nhưng vẫn giữ chất cổ trang khi cần.
5. Giữ nguyên cách chia đoạn của bản gốc. Nếu dòng đầu là tiêu đề chương, dịch tiêu đề cho hay, gọn.
6. Thành ngữ nên dịch thoát ý, tự nhiên, không máy móc.
7. Thơ từ, ca phú, Luận ngữ, trích dẫn cổ văn: nếu nhận ra là câu/bài đã có bản dịch tiếng Việt phổ biến, hãy dùng đúng bản dịch đó và ghi tên dịch giả trong ngoặc ngay sau (vd: "— (bản dịch Tản Đà)"). Nếu không nhận ra bản dịch có sẵn, hãy tự chuyển ngữ sao cho người đọc hiểu được nghĩa, không dịch nguyên xi. TUYỆT ĐỐI không dịch kiểu Vietphrase-một-nghĩa (ghép nghĩa từng chữ máy móc, từ nào dịch được thì dịch từ nào không thì giữ nguyên Hán) — nếu thực sự không thể chuyển ngữ, giữ nguyên cả câu ở dạng phiên âm Hán Việt đầy đủ, không phải kiểu Vietphrase.

Phong cách mong muốn:
- Tông giọng: {tone}
- Mức dùng Hán Việt: {han_viet_level}
- Xử lý tiêu đề: {title_mode}
- Quy tắc ngôi xưng: {pronoun_policy}
- Giữ xuống dòng: {keep_paragraphs}

CHỈ trả về bản dịch tiếng Việt. KHÔNG thêm lời mở đầu, ghi chú, hay giải thích.
{glossary}
--- Nội dung cần dịch ---
{text}"""


TITLE_PROMPT = """Bạn là biên tập tiêu đề cho truyện dịch Trung-Việt. Nhiệm vụ: chuyển ngữ {kind} sau sang tiếng Việt thật HAY, có hồn, KHÔNG dịch sát nghĩa kiểu máy/Quick Translate.

Nguyên tắc bắt buộc:
1. Không bê nguyên âm Hán Việt nếu người đọc Việt không hiểu nghĩa.
2. Có thể đảo cấu trúc, dùng hình ảnh/ẩn dụ tương đương trong tiếng Việt, miễn giữ đúng tinh thần và nội dung cốt lõi.
3. Ví dụ: "Nắm tay người, kéo người đi" nên dịch thành "Tay nắm tay, cùng nhau cất bước" — hay và tự nhiên hơn nhiều so với dịch sát chữ.
4. Nếu thực sự không tìm được cách chuyển ngữ hay mà vẫn giữ đúng nghĩa, hãy dịch nghĩa rõ ràng dù kém mượt hơn là giữ Hán Việt khó hiểu, và điền dòng GIẢI THÍCH để người đọc hiểu nghĩa gốc/lý do chọn từ.

{glossary}
Trả lời ĐÚNG 2 dòng theo định dạng sau, không thêm gì khác:
TIÊU ĐỀ: <bản dịch tiếng Việt>
GIẢI THÍCH: <để trống nếu tên đã rõ nghĩa, tự nhiên; chỉ điền nếu cần giải thích thêm cho người đọc>

--- {kind} cần dịch ---
{text}"""


@dataclass
class CliTranslatorConfig:
    command: str = "claude -p"
    model: str = ""
    mode: str = "stdin"  # stdin | arg
    prompt_template: str = DEFAULT_PROMPT
    title_prompt_template: str = TITLE_PROMPT
    timeout_seconds: int = 300


@dataclass
class TranslateConfig:
    type: str = "cli"  # cli | google | none
    preset: str = ""
    profile: str = "traditional_cn_novel"
    source_language: str = "zh-CN"
    target_language: str = "vi"
    genre: str = ""
    style: TranslationStyleConfig = field(default_factory=TranslationStyleConfig)
    glossary: dict[str, str] = field(default_factory=dict)
    glossary_files: GlossaryFilesConfig = field(default_factory=GlossaryFilesConfig)
    retry: TranslationRetryConfig = field(default_factory=TranslationRetryConfig)
    chunk: TranslationChunkConfig = field(default_factory=TranslationChunkConfig)
    cli: CliTranslatorConfig = field(default_factory=CliTranslatorConfig)
    delay_seconds: float = 0.5


@dataclass
class NovelConfig:
    title: str = ""
    author: str = ""
    language: str = "vi"
    slug: str = "novel"


@dataclass
class OutputConfig:
    data_dir: str = "data"
    epub_path: str = ""


@dataclass
class Config:
    novel: NovelConfig
    crawl: CrawlConfig
    translate: TranslateConfig
    output: OutputConfig
    # Cảnh báo xung đột tính năng phát hiện lúc load config (vd preset ép đổi
    # type, selector không áp dụng cho engine hiện tại...). pipeline.py log
    # các dòng này ra job log để hiện trên web UI thay vì chỉ ghi logging nội bộ.
    warnings: list[str] = field(default_factory=list)

    @property
    def epub_path(self) -> str:
        return self.output.epub_path or f"{self.novel.slug}.epub"


@dataclass
class LibraryEntry:
    slug: str
    name: str = ""
    config: str = ""


@dataclass
class LibraryConfig:
    ebooks: dict[str, LibraryEntry] = field(default_factory=dict)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def load_library(path: str | Path) -> LibraryConfig:
    path = Path(path)
    if not path.exists():
        return LibraryConfig()

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: dict[str, LibraryEntry] = {}
    for slug, item in (raw.get("ebooks") or {}).items():
        data = _as_dict(item)
        if isinstance(item, str):
            data = {"config": item}
        entries[slug] = LibraryEntry(
            slug=slug,
            name=data.get("name", ""),
            config=data.get("config", ""),
        )
    return LibraryConfig(ebooks=entries)


def _build_style(raw: dict[str, Any]) -> TranslationStyleConfig:
    style = _as_dict(raw.get("style"))
    return TranslationStyleConfig(
        tone=style.get("tone", TranslationStyleConfig.tone),
        pronoun_policy=style.get("pronoun_policy", TranslationStyleConfig.pronoun_policy),
        keep_paragraphs=style.get("keep_paragraphs", True),
        title_mode=style.get("title_mode", TranslationStyleConfig.title_mode),
        han_viet_level=style.get("han_viet_level", TranslationStyleConfig.han_viet_level),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {path}")

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base_dir = path.parent

    novel = NovelConfig(**(raw.get("novel") or {}))

    crawl_raw = dict(raw.get("crawl") or {})
    # api_key / api_url chỉ dùng cho firecrawl, đã bỏ engine này; bỏ qua cũ.
    crawl_raw.pop("api_key", None)
    crawl_raw.pop("api_url", None)
    crawl = CrawlConfig(**crawl_raw)

    translate_raw = dict(raw.get("translate") or {})
    preset_name = translate_raw.get("preset", "")
    cli_raw = translate_raw.pop("cli", None) or {}
    style = _build_style(translate_raw)
    glossary_files_raw = _as_dict(translate_raw.pop("glossary_files", None))
    retry_raw = _as_dict(translate_raw.pop("retry", None))
    chunk_raw = _as_dict(translate_raw.pop("chunk", None))
    names_path = glossary_files_raw.get("names", "")
    vietphrase_path = glossary_files_raw.get("vietphrase", "")
    if names_path:
        names_path = str((base_dir / names_path).resolve()) if not Path(names_path).is_absolute() else names_path
    if vietphrase_path:
        vietphrase_path = (
            str((base_dir / vietphrase_path).resolve())
            if not Path(vietphrase_path).is_absolute()
            else vietphrase_path
        )
    # Nếu không khai báo riêng, mặc định dùng đúng thư mục glossary mà
    # Storage/trang web Glossary đang đọc-ghi (data_dir/<slug>/glossary/).
    if not names_path or not vietphrase_path:
        novel_raw = _as_dict(raw.get("novel"))
        output_raw = _as_dict(raw.get("output"))
        slug = novel_raw.get("slug", "novel")
        data_dir = output_raw.get("data_dir", "data")
        data_dir_abs = Path(data_dir) if Path(data_dir).is_absolute() else (base_dir / data_dir).resolve()
        glossary_dir = data_dir_abs / slug / "glossary"
        if not names_path:
            names_path = str(glossary_dir / "names.txt")
        if not vietphrase_path:
            vietphrase_path = str(glossary_dir / "vietphrase.txt")
    warnings: list[str] = []
    if preset_name:
        from . import presets as _presets

        preset_overrides = _presets.load(preset_name)
        merged = dict(preset_overrides)
        merged.update({k: v for k, v in cli_raw.items() if v != "" and v is not None})
        cli_raw = merged
        tr_type = translate_raw.get("type", "cli")
        if tr_type and tr_type != "cli":
            warnings.append(
                f"translate.preset={preset_name!r} đã ép translate.type về 'cli' "
                f"(translate.type={tr_type!r} trong file config bị bỏ qua)."
            )

    translate = TranslateConfig(
        type="cli" if preset_name else translate_raw.get("type", "cli"),
        preset=preset_name,
        profile=translate_raw.get("profile", "traditional_cn_novel"),
        source_language=translate_raw.get("source_language", "zh-CN"),
        target_language=translate_raw.get("target_language", "vi"),
        genre=translate_raw.get("genre", ""),
        style=style,
        glossary=translate_raw.get("glossary") or {},
        glossary_files=GlossaryFilesConfig(
            names=names_path,
            vietphrase=vietphrase_path,
        ),
        retry=TranslationRetryConfig(
            attempts=int(retry_raw.get("attempts", 1)),
            delay_seconds=float(retry_raw.get("delay_seconds", 0.0)),
        ),
        chunk=TranslationChunkConfig(
            max_chars=int(chunk_raw.get("max_chars", 0)),
            overlap_paragraphs=int(chunk_raw.get("overlap_paragraphs", 0)),
        ),
        cli=CliTranslatorConfig(**cli_raw),
        delay_seconds=translate_raw.get("delay_seconds", 0.5),
    )

    output = OutputConfig(**(raw.get("output") or {}))

    if crawl.engine == "crawl4ai":
        ignored_selectors = [
            name for name in (
                "toc_selector", "title_selector", "author_selector",
                "desc_selector", "cover_selector",
            )
            if getattr(crawl, name)
        ]
        if ignored_selectors:
            warnings.append(
                "crawl.engine='crawl4ai' không dùng "
                f"{', '.join(f'crawl.{n}' for n in ignored_selectors)} "
                "(các selector này chỉ áp dụng cho engine 'http')."
            )
    if crawl.ai_fallback and preset_name != "go":
        warnings.append(
            "crawl.ai_fallback=true nhưng translate.preset không phải 'go' "
            f"(hiện tại: {preset_name or '(trống)'!r}) — fallback vẫn dùng prompt "
            "trích xuất HTML của preset 'go', kiểm tra translate.cli có phù hợp không."
        )

    return Config(novel=novel, crawl=crawl, translate=translate, output=output, warnings=warnings)
