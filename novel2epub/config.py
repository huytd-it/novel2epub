"""Đọc và xác thực file cấu hình YAML."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Local NMT model presets ─────────────────────────────────────────
# Key: model_key in novel2epub.hachimimt.translator.MODELS.
# Used when translate.model is set; auto-populates model_key.
LOCAL_MT_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "hachimimt-60": {
        "model_key": "HachimiMT-60",
    },
    "hachimimt-30": {
        "model_key": "HachimiMT-30",
    },
    "moxhimt-60": {
        "model_key": "MoxhiMT-60",
    },
    "moxhimt-30": {
        "model_key": "MoxhiMT-30",
    },
    "hirashiba-medium": {
        "model_key": "HirashibaMT-Medium",
    },
    "hirashiba-tiny": {
        "model_key": "HirashibaMT-Tiny",
    },
}


@dataclass
class CrawlRetryConfig:
    """Thử lại khi tải chương bị chặn vì quá nhiều request (HTTP 429 anti-bot)
    hoặc lỗi mạng tạm thời.

    Khác với `delay_seconds` (giãn cách đều giữa MỌI chương), cấu hình này chỉ
    kích hoạt KHI một chương tải lỗi: chờ lùi dần theo cấp số nhân
    (delay_seconds, ×backoff, ×backoff², ... tối đa max_delay_seconds) rồi thử
    lại, giúp vượt qua chặn tạm thời thay vì bỏ luôn chương.
    """

    # Số lần thử lại sau lần đầu thất bại (0 = không thử lại).
    attempts: int = 3
    # Thời gian chờ ban đầu trước lần thử lại đầu tiên (giây).
    delay_seconds: float = 5.0
    # Hệ số nhân thời gian chờ sau mỗi lần thất bại (1 = chờ đều, 2 = gấp đôi).
    backoff: float = 2.0
    # Trần thời gian chờ một lần (giây) — chặn backoff khỏi phình vô hạn.
    max_delay_seconds: float = 120.0
    # Tôn trọng header `Retry-After` của server (HTTP 429/503) nếu có — chờ đúng
    # số giây server yêu cầu thay vì backoff tự tính.
    respect_retry_after: bool = True


@dataclass
class ScraplingConfig:
    """Cấu hình Scrapling engine. Gom trong `crawl.scrapling:` block."""
    mode: str = "fetcher"                # fetcher | stealthy | dynamic
    solve_cloudflare: bool = False       # chỉ scrapling_mode=stealthy
    network_idle: bool = True            # stealthy/dynamic mode
    impersonate: str = ""                # TLS fingerprint cho fetcher
    # Proxy cho MỌI request crawl (mọi mode) — vượt chặn ISP mà không cần VPN
    # toàn máy. Dạng URL: http://user:pass@host:port | socks5://host:port
    # (vd SOCKS5 qua node Tailscale: socks5://100.x.y.z:1080).
    proxy: str = ""
    # Route DNS qua Cloudflare DNS-over-HTTPS — vượt DNS poisoning của ISP
    # không cần proxy. Chỉ áp dụng mode stealthy/dynamic (browser).
    dns_over_https: bool = False


@dataclass
class CrawlConfig:
    toc_url: str = ""
    chapter_link_pattern: str = r".*"
    max_chapters: int = 0
    strip_patterns: list[str] = field(default_factory=list)
    delay_seconds: float = 1.0
    max_workers: int = 1
    concurrency_cap: int = 0
    retry: CrawlRetryConfig = field(default_factory=CrawlRetryConfig)
    scrapling: ScraplingConfig = field(default_factory=ScraplingConfig)

    def default_concurrency_cap(self) -> int:
        """Trần song song mặc định theo scrapling mode."""
        if self.scrapling.mode == "fetcher":
            return 20
        if self.scrapling.mode in ("stealthy", "dynamic"):
            return 5
        return 20

    def effective_workers(self, requested: int) -> int:
        requested = max(1, int(requested))
        cap = self.concurrency_cap if self.concurrency_cap > 0 else self.default_concurrency_cap()
        return min(requested, max(1, cap))

    # ----- multi-page chapter (pagination) -----
    next_page_selector: str = ""
    next_page_url_pattern: str = ""
    max_pages_per_chapter: int = 10

    # ----- multi-page TOC (pagination) -----
    # CSS selector cho link "trang kế" trên trang mục lục
    toc_next_page_selector: str = ""
    # Số trang mục lục tối đa (1 = chỉ trang đầu, không phân trang)
    toc_max_pages: int = 5

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

    content_selector: str = ""

    # ----- browser settings (Scrapling stealthy/dynamic) -----
    headless: bool = True

    # ----- AI fallback crawl (experimental, cần translate.preset: go) -----
    ai_fallback: bool = False
    ai_fallback_max_html: int = 32000
    _openai_fallback: Any = None  # OpenAIConfig | None


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


@dataclass
class CleanupHanConfig:
    """Cấu hình tự động phát hiện và sửa chữa Hán còn sót sau dịch.

    Kích hoạt: translate.auto_cleanup_han: true
    """
    # Số ký tự tối đa gửi AI mỗi lần (0 = không giới hạn).
    max_chars: int = 8000
    # Số lần thử lại nếu vẫn còn Hán sau cleanup.
    retries: int = 1


DEFAULT_PROMPT = """Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt, theo phong cách edit mượt mà mà độc giả Việt quen thuộc.

Nguyên tắc dịch:
1. Dịch sang tiếng Việt tự nhiên, đúng ngữ pháp Việt: đảo trật tự từ cho thuận, câu đủ chủ-vị.
2. Ngôi xưng theo quan hệ và ngữ cảnh: cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/bà ấy/ngài/người/con/cháu... KHÔNG bê nguyên ta/ngươi.
3. Tên riêng, công pháp, địa danh, chiêu thức: giữ Hán Việt quen thuộc, viết hoa, nhất quán.
4. Hạn chế lạm dụng từ Hán Việt khó hiểu; ưu tiên thuần Việt nếu rõ nghĩa hơn, nhưng giữ chất cổ trang khi cần.
5. Giữ nguyên cách chia đoạn. Nếu dòng đầu là tiêu đề chương, dịch tiêu đề cho hay, gọn.
6. Thành ngữ, tục ngữ, khẩu ngữ: dịch thoát ý bằng cách nói tự nhiên của người Việt, không máy móc (khẩu ngữ chỉ sự e dè thì dịch "ngại", "ngại ngùng"; chê tác phong ăn uống thì "ăn uống khó coi"...).
7. Từ vựng đời thường (động tác, nấu nướng, ăn uống, cảm giác, tiếng lóng...): dịch tự nhiên như văn nói tiếng Việt thông thường, không cần giữ sắc thái Hán, không phiên âm Hán Việt cứng nhắc.
8. Thơ từ, ca phú, trích dẫn cổ văn: nếu có bản dịch phổ biến thì dùng bản dịch đó kèm tên dịch giả (vd: "— (bản dịch Tản Đà)"). Nếu không, tự chuyển ngữ cho người đọc hiểu, không dịch nguyên xi từng chữ kiểu Vietphrase.

Phong cách:
- Tông giọng: {tone}
- Mức Hán Việt: {han_viet_level}
- Xử lý tiêu đề: {title_mode}
- Quy tắc ngôi xưng: {pronoun_policy}
- Giữ xuống dòng: {keep_paragraphs}

CHỈ trả về bản dịch tiếng Việt thuần túy. KHÔNG thêm lời mở đầu, ghi chú, giải thích, hay đánh dấu song ngữ.
KIỂM TRA CUỐI (bắt buộc): trước khi trả lời, rà lại toàn bộ bản dịch từ đầu đến cuối; nếu còn BẤT KỲ ký tự Trung Quốc nào, dịch nốt sang tiếng Việt rồi mới trả lời.
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
class OpenAIConfig:
    """Cấu hình backend AI OpenAI-Compatible — dùng chung cho dịch chương,
    dịch tiêu đề, review/suggest/rewrite/evaluate. Tương thích bất kỳ provider
    nào lộ endpoint kiểu OpenAI (`POST {base_url}/chat/completions`,
    `GET {base_url}/models`): OpenAI, OpenRouter, Ollama (`/v1`), LM Studio,
    vLLM, llama.cpp server, OpenCode Go, v.v.
    """
    base_url: str = "https://opencode.ai/zen/go/v1"
    api_key: str = ""
    model: str = "opencode-go/kimi-k2.6"
    prompt_template: str = DEFAULT_PROMPT
    title_prompt_template: str = TITLE_PROMPT
    timeout_seconds: int = 600
    temperature: float = 0.7


@dataclass
class HachimiMTConfig:
    """Cấu hình backend dịch cục bộ HachimiMT (CTranslate2 + SentencePiece).

    Sử dụng HachimiTranslator từ novel2epub.hachimimt — model được cấu hình
    qua `model_key` (một trong các key của MODELS dict). Backend tự động phát
    hiện CPU/GPU, batch size, thread count qua HardwareProfile.
    """
    # Key trong MODELS dict của HachimiTranslator:
    # "HachimiMT-60" | "HachimiMT-30" | "MoxhiMT-60" | "MoxhiMT-30" |
    # "HirashibaMT-Medium" | "HirashibaMT-Tiny"
    model_key: str = "HachimiMT-60"
    backend: str = "ctranslate2"
    beam_size: int = 2
    chunk_mode: str = "sentence"


@dataclass
class LibreTranslateConfig:
    """Cấu hình backend LibreTranslate (self-hosted translation API).

    Gọi HTTP API `POST /translate` của LibreTranslate server.
    Tương thích với LibreTranslate community instance hoặc self-hosted.
    """
    base_url: str = "http://localhost:5000"
    api_key: str = ""
    source_language: str = ""
    target_language: str = "vi"


@dataclass
class TranslateConfig:
    type: str = "hachimimt"  # hachimimt | openai | google | libretranslate | none
    preset: str = ""
    # Local NMT model: "hachimimt-60" | "hachimimt-30" | "moxhimt-60" | ...
    # Khi set, tự động gán model_key cho HachimiMTConfig.
    # Để trống = dùng model_key mặc định từ hachimimt config.
    model: str = ""
    profile: str = "traditional_cn_novel"
    source_language: str = ""
    target_language: str = "vi"
    genre: str = ""
    style: TranslationStyleConfig = field(default_factory=TranslationStyleConfig)
    glossary: dict[str, str] = field(default_factory=dict)
    glossary_files: GlossaryFilesConfig = field(default_factory=GlossaryFilesConfig)
    retry: TranslationRetryConfig = field(default_factory=TranslationRetryConfig)
    chunk: TranslationChunkConfig = field(default_factory=TranslationChunkConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    hachimimt: HachimiMTConfig = field(default_factory=HachimiMTConfig)
    libretranslate: LibreTranslateConfig = field(default_factory=LibreTranslateConfig)
    delay_seconds: float = 0.5
    # Số chương dịch song song (luồng riêng, dùng chung 1 translator — HTTP
    # request/Google request đều an toàn gọi đồng thời). 1 = tuần tự như trước.
    max_workers: int = 1
    # Khi True + translate.type=openai: sau khi dịch xong từng chương, AI sẽ
    # rút glossary mới từ chính chương đó và merge vào names.txt/vietphrase.txt
    # (in-memory cho chương kế tiếp + ghi file thread-safe). Xung đột (cùng Hán,
    # khác Việt) → giữ giá trị cũ + ghi warning vào log và file tổng kết.
    auto_glossary: bool = False
    # Khi True (mặc định): mỗi lần gọi AI chỉ nhét vào prompt những mục glossary
    # THỰC SỰ xuất hiện trong đoạn đang xử lý (lọc chuỗi con thuần Python, không
    # gọi AI) — tiết kiệm token khi glossary phình to. Bước hậu xử lý
    # _apply_glossary vẫn luôn dùng toàn bộ glossary.
    glossary_filter: bool = True
    # Số chương gửi 1 lần cho AI khi dùng "Dịch selected" (batch translate).
    # Chia nhỏ index thành các batch có kích thước tối đa bằng giá trị này.
    # Đặt 1 = dịch tuần tự từng chương (mỗi chương 1 lần gọi AI).
    batch_size: int = 1
    # Giới hạn TỔNG ký tự của một prompt gửi AI (gồm cả prompt template,
    # glossary và nội dung). Dịch chương: chunk bị thu nhỏ để prompt hoàn chỉnh
    # không vượt giới hạn. Batch dịch: batch bị cắt sớm (ít chương hơn
    # batch_size) khi khối export chạm giới hạn. 0 = không giới hạn.
    prompt_max_chars: int = 7000
    # Tự động chạy cleanup Hán sau mỗi chương được dịch (gọi AI qua config
    # AI biên tập ai.openai — hoạt động với mọi backend dịch).
    auto_cleanup_han: bool = False
    # Cấu hình cleanup Hán.
    cleanup_han: CleanupHanConfig = field(default_factory=CleanupHanConfig)


@dataclass
class NovelConfig:
    title: str = ""
    author: str = ""
    description: str = ""
    language: str = "vi"
    slug: str = "novel"
    # Metadata đóng gói EPUB (Dublin Core + Calibre series/collection) — xem
    # epub_builder.py và spec ebook-metadata. Field rỗng bị epub_builder bỏ
    # qua, không ghi giá trị trống vào EPUB.
    publisher: str = ""
    pubdate: str = ""  # ISO date "YYYY-MM-DD", do người dùng nhập
    date_added: str = ""  # ISO date, tự ghi khi tạo ebook — không cho sửa qua UI
    subjects: list[str] = field(default_factory=list)
    series: str = ""
    series_index: str = ""
    # urn:uuid ổn định qua các lần build lại. Tự sinh khi rỗng (xem
    # `ensure_identifier` trong config_writer.py), người dùng có thể override.
    identifier: str = ""
    # URL ảnh bìa. Người dùng nhập tay hoặc upload file qua Web UI, lưu YAML
    # để pipeline dùng làm cover_url cho manifest khi crawl không có.
    cover_url: str = ""


@dataclass
class AIConfig:
    """Cấu hình AI cho biên tập (glossary suggest/rewrite/evaluate), tách riêng
    khỏi translate.openai để dùng backend khác với backend dịch chương."""
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)


@dataclass
class OutputConfig:
    data_dir: str = "data"
    epub_path: str = ""


@dataclass
class QueueConfig:
    """Số worker thread song song của job queue (app web)."""
    translate_workers: int = 2  # job translate/batch-translate chạy song song
    crawl_workers: int = 2      # job crawl chạy song song


@dataclass
class Config:
    novel: NovelConfig
    crawl: CrawlConfig
    translate: TranslateConfig
    output: OutputConfig
    ai: AIConfig = field(default_factory=AIConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    # Tên source preset mà ebook này tham chiếu. Rỗng = không dùng preset.
    source: str = ""
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


def _deep_merge_raw(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `override` lên `base`, trả về dict mới (không sửa input).

    Dùng để dựng config hiệu lực của một ebook = defaults + phần override riêng.
    """
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_raw(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_source_overrides(
    ebook_raw: dict[str, Any],
    sources_raw: dict[str, Any],
) -> tuple[dict[str, Any], str, list[str]]:
    """Resolve source preset cho ebook, trả về (crawl_merge, source_name, warnings).

    Nếu ebook có field ``source`` và preset tồn tại trong ``sources_raw``,
    trả crawl fields từ preset để caller merge vào config. Nếu preset không
    tồn tại, trả warning và crawl rỗng.
    """
    source_name = str(ebook_raw.get("source", "") or "")
    if not source_name:
        return {}, "", []
    preset_data = _as_dict(sources_raw.get(source_name))
    if not preset_data:
        return {}, source_name, [
            f"source {source_name!r} không tồn tại trong sources — dùng crawl fields từ ebook."
        ]
    from .sources import SourcePreset, _FIELD_NAMES, _coerce

    data = {k: _coerce(k, v) for k, v in preset_data.items() if k in _FIELD_NAMES}
    data["name"] = source_name
    preset = SourcePreset(**data)
    return preset.crawl_overrides(), source_name, []


def load_library(path: str | Path) -> LibraryConfig:
    db_path = Path(path).resolve()
    if not db_path.exists():
        return LibraryConfig()

    from .db import get_thread_connection

    conn = get_thread_connection(db_path)
    entries: dict[str, LibraryEntry] = {}
    for r in conn.execute("SELECT slug, name FROM ebooks ORDER BY slug"):
        entries[r["slug"]] = LibraryEntry(slug=r["slug"], name=r["name"] or "", config="")
    return LibraryConfig(ebooks=entries)


def _load_raw_from_db(conn) -> dict[str, Any]:
    """Dựng lại raw dict {"defaults", "sources", "ebooks"} ĐÚNG cấu trúc YAML
    cũ từ bảng settings/sources/ebooks — để tái dùng nguyên logic merge/parse
    bên dưới (deep-merge, resolve source preset, dataclass construction...
    không đổi gì từ `_deep_merge_raw(defaults, override)` trở xuống)."""
    settings_row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    defaults: dict[str, Any] = {}
    if settings_row:
        for section in ("novel", "crawl", "translate", "ai", "output", "queue"):
            data = json.loads(settings_row[f"{section}_json"] or "{}")
            if data:
                defaults[section] = data

    sources: dict[str, Any] = {}
    for r in conn.execute("SELECT name, data_json FROM sources"):
        sources[r["name"]] = json.loads(r["data_json"] or "{}")

    ebooks: dict[str, Any] = {}
    for r in conn.execute("SELECT * FROM ebooks"):
        block: dict[str, Any] = {}
        if r["name"]:
            block["name"] = r["name"]
        if r["source_preset"]:
            block["source"] = r["source_preset"]
        novel_fields = {
            "slug": r["slug"], "title": r["title"], "author": r["author"],
            "description": r["description"], "language": r["language"],
            "publisher": r["publisher"], "pubdate": r["pubdate"],
            "date_added": r["date_added"],
            "subjects": json.loads(r["subjects_json"] or "[]"),
            "series": r["series"], "series_index": r["series_index"],
            "identifier": r["identifier"], "cover_url": r["cover_url"],
        }
        block["novel"] = {k: v for k, v in novel_fields.items() if v not in (None, "", [])}
        block["novel"]["slug"] = r["slug"]
        crawl_over = json.loads(r["crawl_overrides_json"] or "{}")
        if crawl_over:
            block["crawl"] = crawl_over
        output_over = json.loads(r["output_overrides_json"] or "{}")
        if r["epub_path"] and "epub_path" not in output_over:
            output_over["epub_path"] = r["epub_path"]
        if output_over:
            block["output"] = output_over
        ebooks[r["slug"]] = block

    return {"defaults": defaults, "sources": sources, "ebooks": ebooks}


def _build_style(raw: dict[str, Any]) -> TranslationStyleConfig:
    style = _as_dict(raw.get("style"))
    return TranslationStyleConfig(
        tone=style.get("tone", TranslationStyleConfig.tone),
        pronoun_policy=style.get("pronoun_policy", TranslationStyleConfig.pronoun_policy),
        keep_paragraphs=style.get("keep_paragraphs", True),
        title_mode=style.get("title_mode", TranslationStyleConfig.title_mode),
        han_viet_level=style.get("han_viet_level", TranslationStyleConfig.han_viet_level),
    )


def load_config(path: str | Path, slug: str = "") -> Config:
    from .db import get_thread_connection

    db_path = Path(path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Không tìm thấy DB cấu hình: {db_path}")
    conn = get_thread_connection(db_path)
    base_dir = db_path.parent

    raw_all = _load_raw_from_db(conn)
    defaults = raw_all["defaults"]
    sources_raw = raw_all["sources"]
    ebooks = raw_all["ebooks"]

    if slug:
        if slug not in ebooks:
            raise KeyError(f"không tìm thấy ebook {slug!r} trong {db_path}")
        override = _as_dict(ebooks.get(slug))
    elif ebooks:
        override = _as_dict(next(iter(ebooks.values())))
    else:
        override = {}
    override = dict(override)
    override.pop("name", None)  # tên hiển thị cấp ebook, không thuộc Config
    # `translate` (AI dịch) và `ai` (AI biên tập) là cấu hình DÙNG CHUNG cho
    # mọi ebook — chỉ đọc từ `defaults:`. Override per-ebook (còn sót lại) bị
    # bỏ qua để tránh mỗi ebook một bản cấu hình AI khác nhau.
    override.pop("translate", None)
    override.pop("ai", None)

    # Source preset resolution: nếu ebook có field `source`, lookup preset
    # từ bảng `sources` → merge crawl fields từ preset vào TRƯỚC khi ebook
    # override ghi đè. Source preset = layer giữa defaults và ebook override.
    source_crawl, source_name, source_warnings = _resolve_source_overrides(override, sources_raw)
    override.pop("source", None)  # không đưa vào Config raw dict
    if source_crawl:
        ebook_crawl = _as_dict(override.get("crawl"))
        merged_crawl = _deep_merge_raw(source_crawl, ebook_crawl)
        override["crawl"] = merged_crawl

    raw = _deep_merge_raw(defaults, override)

    novel = NovelConfig(**(raw.get("novel") or {}))
    if not novel.identifier and slug:
        # Sinh + lưu 1 lần urn:uuid ổn định cho ebook chưa có identifier (vd
        # tạo trước khi field này tồn tại) — xem spec ebook-metadata.
        from .config_writer import ensure_identifier

        novel.identifier = ensure_identifier(db_path, slug, "")

    crawl_raw = dict(raw.get("crawl") or {})
    # api_key / api_url chỉ dùng cho firecrawl, đã bỏ engine này; bỏ qua cũ.
    crawl_raw.pop("api_key", None)
    crawl_raw.pop("api_url", None)
    # Legacy engine field — scrapling là engine duy nhất.
    crawl_raw.pop("engine", None)
    # Field cũ (http/crawl4ai) — bỏ qua không báo lỗi để migration mượt.
    for old in ("toc_selector", "chapter_title_selector", "title_selector",
                "author_selector", "desc_selector", "cover_selector",
                "encoding", "user_agent", "js_code", "magic", "stealth"):
        crawl_raw.pop(old, None)
    # Legacy scrapling fields → map vào ScraplingConfig
    legacy_scrapling_mode = crawl_raw.pop("scrapling_mode", None)
    legacy_solve_cf = crawl_raw.pop("solve_cloudflare", None)
    legacy_network_idle = crawl_raw.pop("network_idle", None)
    legacy_impersonate = crawl_raw.pop("impersonate", None)
    legacy_proxy = crawl_raw.pop("proxy", None)
    legacy_doh = crawl_raw.pop("dns_over_https", None)
    scrapling_raw = _as_dict(crawl_raw.pop("scrapling", None))
    if legacy_scrapling_mode and "mode" not in scrapling_raw:
        scrapling_raw["mode"] = legacy_scrapling_mode
    if legacy_solve_cf is not None and "solve_cloudflare" not in scrapling_raw:
        scrapling_raw["solve_cloudflare"] = legacy_solve_cf
    if legacy_network_idle is not None and "network_idle" not in scrapling_raw:
        scrapling_raw["network_idle"] = legacy_network_idle
    if legacy_impersonate and "impersonate" not in scrapling_raw:
        scrapling_raw["impersonate"] = legacy_impersonate
    if legacy_proxy and "proxy" not in scrapling_raw:
        scrapling_raw["proxy"] = legacy_proxy
    if legacy_doh is not None and "dns_over_https" not in scrapling_raw:
        scrapling_raw["dns_over_https"] = legacy_doh
    crawl_retry_raw = _as_dict(crawl_raw.pop("retry", None))
    crawl = CrawlConfig(**crawl_raw)
    if scrapling_raw:
        crawl.scrapling = ScraplingConfig(**scrapling_raw)
    if crawl_retry_raw:
        defaults_rc = CrawlRetryConfig()
        crawl.retry = CrawlRetryConfig(
            attempts=int(crawl_retry_raw.get("attempts", defaults_rc.attempts)),
            delay_seconds=float(crawl_retry_raw.get("delay_seconds", defaults_rc.delay_seconds)),
            backoff=float(crawl_retry_raw.get("backoff", defaults_rc.backoff)),
            max_delay_seconds=float(crawl_retry_raw.get("max_delay_seconds", defaults_rc.max_delay_seconds)),
            respect_retry_after=bool(crawl_retry_raw.get("respect_retry_after", defaults_rc.respect_retry_after)),
        )

    translate_raw = dict(raw.get("translate") or {})
    preset_name = translate_raw.get("preset", "")
    openai_raw = translate_raw.pop("openai", None) or {}
    hachimimt_raw = _as_dict(translate_raw.pop("hachimimt", None))
    libretranslate_raw = _as_dict(translate_raw.pop("libretranslate", None))
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
    warnings: list[str] = list(source_warnings)
    if preset_name:
        from . import presets as _presets

        preset_overrides = _presets.load(preset_name)
        merged = dict(preset_overrides)
        merged.update({k: v for k, v in openai_raw.items() if v != "" and v is not None})
        openai_raw = merged

    # Resolve local NMT model preset: translate.model tên preset → model_key.
    translate_model = translate_raw.get("model", "") or ""
    hachimimt = HachimiMTConfig(**hachimimt_raw) if hachimimt_raw else HachimiMTConfig()
    if translate_model:
        preset = LOCAL_MT_MODEL_PRESETS.get(translate_model)
        if preset:
            mk = preset.get("model_key")
            if mk and "model_key" not in hachimimt_raw:
                hachimimt.model_key = mk
        else:
            warnings.append(
                f"translate.model {translate_model!r} không hợp lệ "
                f"(chọn: {', '.join(LOCAL_MT_MODEL_PRESETS)}). Dùng raw config."
            )

    cleanup_han_raw = _as_dict(translate_raw.pop("cleanup_han", None))
    translate = TranslateConfig(
        type=translate_raw.get("type", "hachimimt"),
        model=translate_model,
        preset=preset_name,
        profile=translate_raw.get("profile", "traditional_cn_novel"),
        source_language=translate_raw.get("source_language", ""),
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
        openai=OpenAIConfig(**openai_raw),
        hachimimt=hachimimt,
        libretranslate=LibreTranslateConfig(**libretranslate_raw) if libretranslate_raw else LibreTranslateConfig(),
        delay_seconds=translate_raw.get("delay_seconds", 0.5),
        max_workers=int(translate_raw.get("max_workers", 1)),
        auto_glossary=bool(translate_raw.get("auto_glossary", False)),
        glossary_filter=bool(translate_raw.get("glossary_filter", True)),
        batch_size=int(translate_raw.get("batch_size", 1)),
        prompt_max_chars=int(translate_raw.get("prompt_max_chars", 7000)),
        auto_cleanup_han=bool(translate_raw.get("auto_cleanup_han", False)),
        cleanup_han=CleanupHanConfig(
            max_chars=int(cleanup_han_raw.get("max_chars", CleanupHanConfig.max_chars)),
            retries=int(cleanup_han_raw.get("retries", CleanupHanConfig.retries)),
        ),
    )

    output_raw = dict(raw.get("output") or {})
    # `data_dir` PHẢI luôn là thư mục chứa chính file DB đang đọc (base_dir) —
    # đảm bảo Storage(cfg.output.data_dir, slug) resolve về ĐÚNG file .db này
    # (xem novel2epub/storage.py:resolve_db_path), không phụ thuộc giá trị cũ
    # còn sót trong settings.output_json (vốn chỉ còn ý nghĩa hiển thị).
    output_raw["data_dir"] = str(base_dir)
    output = OutputConfig(**output_raw)

    # --- AI (biên tập) config — fallback về translate.openai nếu không có khối `ai:` ---
    ai_raw = raw.get("ai") or {}
    ai_openai_raw = _as_dict(ai_raw.get("openai"))
    if not ai_openai_raw:
        # Chưa có ai.openai → dùng translate.openai làm mặc định (backward-compat)
        ai_openai_raw = openai_raw
    ai = AIConfig(openai=OpenAIConfig(**ai_openai_raw))

    if crawl.ai_fallback and preset_name != "go":
        warnings.append(
            "crawl.ai_fallback=true nhưng translate.preset không phải 'go' "
            f"(hiện tại: {preset_name or '(trống)'!r}) — fallback vẫn dùng prompt "
            "trích xuất HTML của preset 'go', kiểm tra translate.openai có phù hợp không."
        )

    if crawl.scrapling.solve_cloudflare and crawl.scrapling.mode != "stealthy":
        warnings.append(
            f"crawl.scrapling.solve_cloudflare=true nhưng mode={crawl.scrapling.mode!r} "
            "— cờ này BỊ BỎ QUA, chỉ mode 'stealthy' mới dùng được. Trang bị "
            "Cloudflare chặn sẽ trả về HTML thử thách ('Just a moment...') và mục "
            "lục ra 0 chương."
        )

    queue_raw = _as_dict(raw.get("queue"))
    defaults_q = QueueConfig()
    queue = QueueConfig(
        translate_workers=max(1, int(queue_raw.get("translate_workers", defaults_q.translate_workers))),
        crawl_workers=max(1, int(queue_raw.get("crawl_workers", defaults_q.crawl_workers))),
    )

    return Config(novel=novel, crawl=crawl, translate=translate, ai=ai, output=output, queue=queue, source=source_name, warnings=warnings)
