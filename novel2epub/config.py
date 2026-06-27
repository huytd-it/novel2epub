"""Đọc và xác thực file cấu hình YAML."""
from __future__ import annotations

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

import yaml


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


@dataclass
class CrawlConfig:
    toc_url: str
    engine: str = "scrapling"
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
class OpenAIConfig:
    """Cấu hình backend AI OpenAI-Compatible — dùng chung cho dịch chương,
    dịch tiêu đề, review/suggest/rewrite/evaluate. Tương thích bất kỳ provider
    nào lộ endpoint kiểu OpenAI (`POST {base_url}/chat/completions`,
    `GET {base_url}/models`): OpenAI, OpenRouter, Ollama (`/v1`), LM Studio,
    vLLM, llama.cpp server, v.v.
    """
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    prompt_template: str = DEFAULT_PROMPT
    title_prompt_template: str = TITLE_PROMPT
    timeout_seconds: int = 300
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
class TranslateConfig:
    type: str = "hachimimt"  # hachimimt | openai | google | none
    preset: str = ""
    # Local NMT model: "hachimimt-60" | "hachimimt-30" | "moxhimt-60" | ...
    # Khi set, tự động gán model_key cho HachimiMTConfig.
    # Để trống = dùng model_key mặc định từ hachimimt config.
    model: str = ""
    profile: str = "traditional_cn_novel"
    source_language: str = "zh-CN"
    target_language: str = "vi"
    genre: str = ""
    style: TranslationStyleConfig = field(default_factory=TranslationStyleConfig)
    glossary: dict[str, str] = field(default_factory=dict)
    glossary_files: GlossaryFilesConfig = field(default_factory=GlossaryFilesConfig)
    retry: TranslationRetryConfig = field(default_factory=TranslationRetryConfig)
    chunk: TranslationChunkConfig = field(default_factory=TranslationChunkConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    hachimimt: HachimiMTConfig = field(default_factory=HachimiMTConfig)
    delay_seconds: float = 0.5
    # Số chương dịch song song (luồng riêng, dùng chung 1 translator — HTTP
    # request/Google request đều an toàn gọi đồng thời). 1 = tuần tự như trước.
    max_workers: int = 1


@dataclass
class NovelConfig:
    title: str = ""
    author: str = ""
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
            # File gộp: ebook nằm inline trong cùng file (không còn `config:` riêng).
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


def load_config(path: str | Path, slug: str = "") -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {path}")

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base_dir = path.parent
    is_unified = "ebooks" in raw

    # Chế độ "unified": file gộp có khối `ebooks:` -> config hiệu lực của một
    # ebook = deep_merge(defaults, ebooks[slug]). Không có `ebooks:` thì coi như
    # file phẳng cũ (novel/crawl/translate/output ở top-level), giữ nguyên hành vi.
    if is_unified:
        defaults = _as_dict(raw.get("defaults"))
        ebooks = _as_dict(raw.get("ebooks"))
        if slug:
            if slug not in ebooks:
                raise KeyError(f"không tìm thấy ebook {slug!r} trong {path}")
            override = _as_dict(ebooks.get(slug))
        elif ebooks:
            override = _as_dict(next(iter(ebooks.values())))
        else:
            override = {}
        override = dict(override)
        override.pop("name", None)  # tên hiển thị cấp ebook, không thuộc Config
        raw = _deep_merge_raw(defaults, override)

    novel = NovelConfig(**(raw.get("novel") or {}))
    if not novel.identifier and is_unified and slug:
        # Sinh + lưu 1 lần urn:uuid ổn định cho ebook chưa có identifier (vd
        # tạo trước khi field này tồn tại) — xem spec ebook-metadata.
        from .config_writer import ensure_identifier

        novel.identifier = ensure_identifier(path, slug, "")

    crawl_raw = dict(raw.get("crawl") or {})
    # api_key / api_url chỉ dùng cho firecrawl, đã bỏ engine này; bỏ qua cũ.
    crawl_raw.pop("api_key", None)
    crawl_raw.pop("api_url", None)
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
    scrapling_raw = _as_dict(crawl_raw.pop("scrapling", None))
    if legacy_scrapling_mode and "mode" not in scrapling_raw:
        scrapling_raw["mode"] = legacy_scrapling_mode
    if legacy_solve_cf is not None and "solve_cloudflare" not in scrapling_raw:
        scrapling_raw["solve_cloudflare"] = legacy_solve_cf
    if legacy_network_idle is not None and "network_idle" not in scrapling_raw:
        scrapling_raw["network_idle"] = legacy_network_idle
    if legacy_impersonate and "impersonate" not in scrapling_raw:
        scrapling_raw["impersonate"] = legacy_impersonate
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

    translate = TranslateConfig(
        type=translate_raw.get("type", "hachimimt"),
        model=translate_model,
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
        openai=OpenAIConfig(**openai_raw),
        hachimimt=hachimimt,
        delay_seconds=translate_raw.get("delay_seconds", 0.5),
        max_workers=int(translate_raw.get("max_workers", 1)),
    )

    output = OutputConfig(**(raw.get("output") or {}))

    if crawl.ai_fallback and preset_name != "go":
        warnings.append(
            "crawl.ai_fallback=true nhưng translate.preset không phải 'go' "
            f"(hiện tại: {preset_name or '(trống)'!r}) — fallback vẫn dùng prompt "
            "trích xuất HTML của preset 'go', kiểm tra translate.openai có phù hợp không."
        )

    return Config(novel=novel, crawl=crawl, translate=translate, output=output, warnings=warnings)
