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
    max_chars: int = 18000
    # Số lần thử lại nếu vẫn còn Hán sau cleanup.
    retries: int = 1


DEFAULT_PROMPT = """Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt. Hãy tạo bản dịch mượt mà, tự nhiên, đúng nghĩa và phù hợp với cách đọc của độc giả Việt.

NGUYÊN TẮC DỊCH

1. NGỮ NGHĨA VÀ CÂU VĂN
- Dịch đầy đủ nội dung, không tự ý thêm, bớt hoặc giải thích.
- Viết theo ngữ pháp tiếng Việt tự nhiên; được phép đảo trật tự từ, tách hoặc nối câu khi cần để câu rõ nghĩa và mượt.
- Không dịch sát từng chữ hoặc giữ cấu trúc câu tiếng Trung nếu làm câu tiếng Việt cứng, tối nghĩa.

2. NGÔI KỂ VÀ XƯNG HÔ
Thứ tự ưu tiên bắt buộc: BẢNG NHÂN VẬT > ngôi kể thực tế của đoạn > quan hệ/ngữ cảnh > gợi ý thể loại.

- [LỜI KỂ NGÔI BA] Chọn cách gọi theo điểm nhìn, giới tính, sắc thái và khoảng cách trần thuật. Có thể dùng "hắn" khi tự nhiên và nhất quán, kể cả trong truyện hiện đại; không bắt buộc đổi thành "anh", "anh ta" hoặc "anh ấy". Tuy nhiên, không thay mọi 他 bằng "hắn": có thể dùng tên riêng, danh xưng, đại từ khác hoặc lược chủ ngữ khi tự nhiên và không gây nhầm lẫn. Giữ hệ thống quy chiếu nhất quán nhưng tránh lặp đại từ dày đặc.
- [LỜI KỂ NGÔI MỘT / NGÔI HAI] Giữ đúng giọng người kể. "Ta/ngươi" chỉ dùng khi phù hợp với thời đại, thân phận, tính cách và sắc thái; không phải lựa chọn mặc định.
- [THOẠI] Chọn xưng hô theo quan hệ có hướng giữa người nói và người nghe: tuổi tác, vai vế, thân phận, mức thân sơ, cảm xúc và giai đoạn quan hệ. "Ta/ngươi" hợp lệ khi đúng bối cảnh, nhưng không ánh xạ máy móc mọi 我/你 thành "ta/ngươi". Ưu tiên danh xưng đặc thù như cha, mẹ, sư phụ, đồ nhi, huynh, muội, tiền bối, vãn bối, ngài... khi quan hệ yêu cầu.
- [NỘI TÂM] Dùng cách nhân vật tự gọi mình. Nội tâm có thể dùng "ta" dù lời kể bên ngoài dùng ngôi ba, nếu đúng giọng nhân vật.
- [HỆ THỐNG] Giữ giọng máy móc, không cảm xúc; dùng "Ký chủ" hoặc "Người chơi" khi đúng ngữ cảnh.
- Không ánh xạ đại từ một-một: 我 không mặc định là "ta"; 你 không mặc định là "ngươi"; 他 không mặc định là "hắn". Luôn chọn theo chức năng của câu và ngữ cảnh cụ thể.

3. TÊN RIÊNG VÀ THUẬT NGỮ
- Tên người Trung Quốc, địa danh, môn phái, công pháp, cảnh giới và chiêu thức: dùng dạng Hán Việt quen thuộc, viết hoa và giữ nhất quán.
- Tên người nước ngoài được phiên âm bằng chữ Hán: trả về dạng Latin gốc khi nhận diện chắc chắn, ví dụ 夏洛克 → Sherlock, 鸣人 → Naruto, 小樱 → Sakura.
- Không chắc tên Latin gốc thì dùng phương án an toàn theo glossary hoặc quy tắc Hán Việt; không tự bịa.

4. HÁN VIỆT VÀ THUẦN VIỆT
- Hạn chế từ Hán Việt khó hiểu khi có cách nói thuần Việt rõ ràng hơn.
- Giữ sắc thái Hán Việt cần thiết trong truyện cổ trang, tiên hiệp, huyền huyễn và các khái niệm thuộc thế giới truyện.
- Từ đời thường, động tác, cảm giác, ăn uống, nấu nướng và tiếng lóng phải được diễn đạt tự nhiên như tiếng Việt thông thường.

5. THÀNH NGỮ VÀ VĂN BẢN ĐẶC BIỆT
- Thành ngữ, tục ngữ và khẩu ngữ: dịch theo ý và sắc thái, không ghép nghĩa từng chữ.
- Thơ, ca phú và trích dẫn cổ văn: dùng bản dịch tiếng Việt phổ biến nếu nhận diện chắc chắn; nếu không, chuyển ngữ rõ nghĩa và có văn phong phù hợp.
- Không để lại câu Vietphrase hoặc chữ Hán chưa dịch.

6. ĐỊNH DẠNG
- Giữ nguyên cách chia đoạn.
- Nếu dòng đầu là tiêu đề chương, dịch tiêu đề gọn, tự nhiên và có ý vị.
- Chỉ trả về bản dịch tiếng Việt; không thêm lời mở đầu, ghi chú, giải thích hoặc đánh dấu song ngữ.

PHONG CÁCH THEO CẤU HÌNH
- Tông giọng: {tone}
- Mức Hán Việt: {han_viet_level}
- Xử lý tiêu đề: {title_mode}
- Gợi ý thể loại và chính sách xưng hô bổ sung:
{pronoun_policy}
- Giữ xuống dòng: {keep_paragraphs}

KIỂM TRA CUỐI
- Đã dịch đầy đủ, không thêm hoặc bỏ ý.
- Ngôi kể và xưng hô nhất quán, đúng quan hệ.
- Không thay "hắn/ta/ngươi" chỉ vì định kiến thể loại; cũng không lạm dụng chúng.
- Không còn ký tự Trung Quốc chưa dịch.
- Đầu ra chỉ chứa bản dịch tiếng Việt.
{glossary}
{idioms}
{characters}
--- Nội dung cần dịch ---
{text}{auto_glossary_block}"""


TITLE_PROMPT = """Bạn là biên tập tiêu đề cho truyện dịch Trung-Việt. Nhiệm vụ: chuyển ngữ {kind} sau sang tiếng Việt thật HAY, có hồn, KHÔNG dịch sát nghĩa kiểu máy/Quick Translate.

Nguyên tắc bắt buộc:
1. Không bê nguyên âm Hán Việt nếu người đọc Việt không hiểu nghĩa.
2. Có thể đảo cấu trúc, dùng hình ảnh/ẩn dụ tương đương trong tiếng Việt, miễn giữ đúng tinh thần và nội dung cốt lõi.
3. Ví dụ: "Nắm tay người, kéo người đi" nên dịch thành "Tay nắm tay, cùng nhau cất bước" — hay và tự nhiên hơn nhiều so với dịch sát chữ.
4. Tên người nước ngoài giữ dạng chữ Latin gốc (夏洛克 → Sherlock, 鸣人 → Naruto), không chuyển Hán Việt.
5. Nếu thực sự không tìm được cách chuyển ngữ hay mà vẫn giữ đúng nghĩa, hãy dịch nghĩa rõ ràng dù kém mượt hơn là giữ Hán Việt khó hiểu, và điền dòng GIẢI THÍCH để người đọc hiểu nghĩa gốc/lý do chọn từ.

{glossary}
Trả lời ĐÚNG 2 dòng theo định dạng sau, không thêm gì khác:
TIÊU ĐỀ: <bản dịch tiếng Việt>
GIẢI THÍCH: <để trống nếu tên đã rõ nghĩa, tự nhiên; chỉ điền nếu cần giải thích thêm cho người đọc>

--- {kind} cần dịch ---
{text}"""


EN_DEFAULT_PROMPT = """You are a professional literary translator converting an English web novel into Vietnamese. Produce a faithful, fluent translation that reads naturally to Vietnamese readers.

TRANSLATION RULES

1. MEANING AND PROSE
- Translate all content without adding, omitting, or explaining it.
- Restructure, split, or join sentences when needed for clear and natural Vietnamese.
- Do not preserve English syntax when it makes the Vietnamese stiff or ambiguous.

2. NARRATIVE PERSON AND FORMS OF ADDRESS
Mandatory priority: CHARACTER TABLE > the passage's actual narrative person > relationship/context > genre suggestions.

- [THIRD-PERSON NARRATION] Choose references by viewpoint, gender, tone, and narrative distance. "Hắn" is valid when natural, including in modern fiction; do not mechanically replace it with "anh", "anh ta", or "anh ấy". Do not translate every he/him as "hắn": use names, titles, other suitable references, or omit the subject when natural and unambiguous. Keep references consistent without repeating pronouns excessively.
- [FIRST-/SECOND-PERSON NARRATION] Preserve the narrator's voice. Use "ta/ngươi" only when period, status, personality, and tone support it; they are not defaults for first or second person.
- [DIALOGUE] Choose forms of address from the directed relationship between speaker and listener: age, rank, status, intimacy, emotion, and relationship stage. "Ta/ngươi" is valid in the right context, but never map I/you to it mechanically. Prefer relationship-specific terms such as cha, mẹ, sư phụ, đồ nhi, huynh, muội, tiền bối, vãn bối, or ngài when required.
- [INNER THOUGHT] Use how the character refers to themself. Inner thought may use "ta" while external narration remains third person when that matches the character's voice.
- [SYSTEM MESSAGE] Keep a mechanical, emotionless voice; use "Ký chủ" or "Người chơi" when appropriate.
- Never map source pronouns one-to-one. Choose Vietnamese references by each sentence's function and context.

3. NAMES AND TERMS
- Use familiar Hán Việt forms for Chinese names, places, sects, techniques, realms, and setting-specific terms; capitalize proper names consistently.
- For established pinyin or English renderings, resolve them to familiar Hán Việt forms only when confident (for example, Xie Lian → Tạ Liên and Wei Wuxian → Ngụy Vô Tiện). Otherwise keep the source spelling; do not invent a name.

4. HÁN VIỆT AND NATURAL VIETNAMESE
- Avoid obscure Hán Việt when clear Vietnamese is more natural.
- Preserve appropriate Hán Việt flavor in historical, xianxia, fantasy, and setting-specific concepts.
- Render everyday actions, sensations, food, body language, and slang as natural Vietnamese.

5. IDIOMS AND SPECIAL TEXT
- Translate idioms, colloquialisms, and slang by meaning and tone, not word-for-word.
- Use a recognized Vietnamese rendering for poetry or classical quotations only when confident; otherwise translate clearly in a suitable style.

6. FORMAT
- Preserve paragraph breaks.
- If the first line is a chapter title, translate it concisely and naturally.
- Return only the Vietnamese translation, with no preamble, notes, explanation, or bilingual annotation.

CONFIGURED STYLE
- Tone: {tone}
- Hán Việt level: {han_viet_level}
- Title handling: {title_mode}
- Additional genre and pronoun guidance:
{pronoun_policy}
- Preserve line breaks: {keep_paragraphs}

FINAL CHECK
- The translation is complete and faithful.
- Narrative person and forms of address are consistent with relationships.
- "Hắn/ta/ngươi" were neither rejected because of genre nor overused.
- The output contains only the Vietnamese translation.
{glossary}
{idioms}
{characters}
--- Content to translate ---
{text}{auto_glossary_block}"""


EN_TITLE_PROMPT = """You are a title editor for English-to-Vietnamese translated novels. Task: translate the following {kind} into Vietnamese that is BEAUTIFUL and NATURAL, NOT a stiff machine translation.

Mandatory rules:
1. Do not keep English words when a Vietnamese equivalent sounds better.
2. You may restructure, use metaphors or imagery natural to Vietnamese, as long as the core meaning is preserved.
3. Character names: resolve pinyin/English-gloss names to familiar Hán Việt when confident (e.g. "Xie Lian" → "Tạ Liên"), otherwise keep as-is.
4. If you truly cannot find a good translation that preserves meaning, translate for clarity even if less poetic, and fill in the GIẢI THÍCH line to explain.

{glossary}
Reply EXACTLY 2 lines in this format, nothing else:
TIÊU ĐỀ: <Vietnamese translation>
GIẢI THÍCH: <leave blank if name is already clear/natural; only fill if extra explanation helps readers>

--- {kind} to translate ---
{text}"""


@dataclass
class OpenAIConfig:
    """Cấu hình backend AI OpenAI-Compatible — dùng chung cho dịch chương,
    dịch tiêu đề, review/suggest/rewrite/evaluate. Tương thích bất kỳ provider
    nào lộ endpoint kiểu OpenAI (`POST {base_url}/chat/completions`,
    `GET {base_url}/models`): OpenAI, OpenRouter, Ollama (`/v1`), LM Studio,
    vLLM, llama.cpp server, OpenCode Go, v.v.
    """
    base_url: str = "http://localhost:20128/v1"
    api_key: str = ""
    model: str = "free-stack"
    prompt_template: str = DEFAULT_PROMPT
    title_prompt_template: str = TITLE_PROMPT
    timeout_seconds: int = 120000
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
    type: str = "openai"  # openai | hachimimt | google | libretranslate | none
    preset: str = ""
    # Local NMT model: "hachimimt-60" | "hachimimt-30" | "moxhimt-60" | ...
    # Khi set, tự động gán model_key cho HachimiMTConfig.
    # Để trống = dùng model_key mặc định từ hachimimt config.
    model: str = ""
    profile: str = "traditional_cn_novel"
    source_language: str = ""
    target_language: str = "vi"
    genre: str = "auto"
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
    auto_glossary: bool = True
    # Khi True (mặc định): mỗi lần gọi AI chỉ nhét vào prompt những mục glossary
    # THỰC SỰ xuất hiện trong đoạn đang xử lý (lọc chuỗi con thuần Python, không
    # gọi AI) — tiết kiệm token khi glossary phình to. Bước hậu xử lý
    # _apply_glossary vẫn luôn dùng toàn bộ glossary.
    glossary_filter: bool = True
    # Bật từ điển idiom/thành ngữ DÙNG CHUNG (bảng `idioms`, global mọi ebook):
    # LLM nhận idiom làm tham chiếu trong prompt; MT 57M hậu-chuẩn-hoá
    # literal→natural + protect zh→placeholder. Tắt = bỏ qua toàn bộ idiom.
    use_idioms: bool = True
    # Số chương gửi 1 lần cho AI khi dùng "Dịch selected" (batch translate).
    # Chia nhỏ index thành các batch có kích thước tối đa bằng giá trị này.
    # Đặt 1 = dịch tuần tự từng chương (mỗi chương 1 lần gọi AI).
    batch_size: int = 1
    # Giới hạn TỔNG ký tự của một prompt gửi AI (gồm cả prompt template,
    # glossary và nội dung). Dịch chương: chunk bị thu nhỏ để prompt hoàn chỉnh
    # không vượt giới hạn. Batch dịch: batch bị cắt sớm (ít chương hơn
    # batch_size) khi khối export chạm giới hạn. 0 = không giới hạn.
    prompt_max_chars: int = 0
    # Tự động chạy cleanup Hán sau mỗi chương được dịch (gọi AI qua config
    # AI biên tập ai.openai — hoạt động với mọi backend dịch).
    auto_cleanup_han: bool = False
    # AI glossary analysis per-ebook (opt-in, makes translation slower).
    # When True: run AI glossary extraction/merge/cleanup/eval per chapter.
    # When False: use glossary as-is (fast path). Typically enabled only for
    # new domains not yet in source presets.
    ai_glossary_analysis: bool = False
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
class ApiConfig:
    """Truy cập API/OPDS từ ngoài localhost (tích hợp readest).

    `token` dùng chung mọi ebook. Request từ localhost được miễn token nên
    web UI và readest desktop chạy cùng máy không cần cấu hình gì.
    `cors_origins` chỉ cần cho bản readest WEB — Tauri desktop/mobile gọi
    HTTP native, không đi qua CORS. TUYỆT ĐỐI không dùng "*".
    """
    token: str = ""
    cors_origins: list[str] = field(default_factory=list)
    # Khi catalog OPDS được gọi, tự đẩy job build NỀN cho ebook chưa build
    # hoặc có bản dịch mới hơn file EPUB. Request feed KHÔNG chờ job — sách
    # mới sẽ có mặt ở lần làm mới sau. Tắt cờ này thì quay về build tay.
    auto_build: bool = True


# Các field của `reader` CHỈ đọc từ `defaults:` — override per-ebook bị bỏ đi
# lúc load (xem `load_config`). Chủ yếu để `service_key` chỉ nằm ĐÚNG MỘT chỗ.
READER_GLOBAL_FIELDS = ("url", "service_key", "timeout_seconds", "batch_size")


@dataclass
class ReaderConfig:
    """Đẩy chương lên app đọc novel-reader (Supabase PostgREST).

    `url`/`service_key`/`timeout_seconds`/`batch_size` dùng chung mọi ebook
    (chỉ đọc từ `defaults:`); `slug`/`free_chapters`/`published` đặt riêng
    từng ebook.
    """
    # ── dùng chung ──
    url: str = ""            # https://<ref>.supabase.co
    service_key: str = ""    # service_role key — bypass RLS, TUYỆT ĐỐI không log
    timeout_seconds: int = 60
    batch_size: int = 50
    # ── theo ebook ──
    slug: str = ""           # books.slug bên Reader; rỗng = dùng novel.slug
    free_chapters: int = 5   # số chương đầu đọc miễn phí (như cờ --free của ingest-epub.ts)
    published: bool = False  # books.is_published, chỉ set khi tạo sách lần đầu

    @property
    def configured(self) -> bool:
        return bool(self.url and self.service_key)


@dataclass
class Config:
    novel: NovelConfig
    crawl: CrawlConfig
    translate: TranslateConfig
    output: OutputConfig
    ai: AIConfig = field(default_factory=AIConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    reader: ReaderConfig = field(default_factory=ReaderConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
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
        for section in ("novel", "crawl", "translate", "ai", "output", "queue", "reader", "api"):
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
        reader_over = json.loads(r["reader_overrides_json"] or "{}")
        if reader_over:
            block["reader"] = reader_over
        translate_over = json.loads(r["translate_overrides_json"] or "{}")
        if translate_over:
            block["translate"] = translate_over
        ai_over = json.loads(r["ai_overrides_json"] or "{}")
        if ai_over:
            block["ai"] = ai_over
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
    # `translate` (AI dịch) và `ai` (AI biên tập) là cấu hình RIÊNG từng ebook
    # (translate_overrides_json/ai_overrides_json) merge đè lên `defaults:` —
    # defaults chỉ còn là fallback cho ebook chưa cấu hình riêng và là giá trị
    # quay về khi bấm Reset.
    # `reader` merge được per-ebook (slug/free_chapters/published), NHƯNG phần
    # kết nối Supabase thì không — giữ `service_key` ở đúng một chỗ (defaults).
    ebook_reader = _as_dict(override.get("reader"))
    if ebook_reader:
        override["reader"] = {
            k: v for k, v in ebook_reader.items() if k not in READER_GLOBAL_FIELDS
        }

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
    translate_raw.pop("glossary_files", None)  # deprecated: glossary is SQLite-only
    retry_raw = _as_dict(translate_raw.pop("retry", None))
    chunk_raw = _as_dict(translate_raw.pop("chunk", None))
    warnings: list[str] = list(source_warnings)
    if preset_name:
        from . import presets as _presets

        preset_overrides = _presets.load(preset_name)
        merged = dict(preset_overrides)
        merged.update({k: v for k, v in openai_raw.items() if v != "" and v is not None})
        openai_raw = merged

    # EN source: auto-select EN prompts (same mechanism as preset resolution).
    # Explicit non-empty user values still win.
    _src_lang = translate_raw.get("source_language", "")
    if _src_lang == "en":
        _en_overrides = {"prompt_template": EN_DEFAULT_PROMPT, "title_prompt_template": EN_TITLE_PROMPT}
        for _k, _v in _en_overrides.items():
            if not openai_raw.get(_k):
                openai_raw[_k] = _v

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
        type=translate_raw.get("type", TranslateConfig.type),
        model=translate_model,
        preset=preset_name,
        profile=translate_raw.get("profile", "traditional_cn_novel"),
        source_language=translate_raw.get("source_language", ""),
        target_language=translate_raw.get("target_language", "vi"),
        genre=translate_raw.get("genre", ""),
        style=style,
        glossary=translate_raw.get("glossary") or {},
        glossary_files=GlossaryFilesConfig(),
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
        auto_glossary=bool(translate_raw.get("auto_glossary", True)),
        glossary_filter=True,  # ponytail: luôn bật, bypass config
        use_idioms=bool(translate_raw.get("use_idioms", True)),
        batch_size=int(translate_raw.get("batch_size", 1)),
        prompt_max_chars=int(translate_raw.get("prompt_max_chars", 20000)),
        auto_cleanup_han=bool(translate_raw.get("auto_cleanup_han", False)),
        ai_glossary_analysis=bool(translate_raw.get("ai_glossary_analysis", False)),
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

    reader_raw = _as_dict(raw.get("reader"))
    defaults_r = ReaderConfig()
    reader = ReaderConfig(
        url=str(reader_raw.get("url", defaults_r.url)).strip().rstrip("/"),
        service_key=str(reader_raw.get("service_key", defaults_r.service_key)).strip(),
        timeout_seconds=max(1, int(reader_raw.get("timeout_seconds", defaults_r.timeout_seconds))),
        batch_size=max(1, int(reader_raw.get("batch_size", defaults_r.batch_size))),
        # Rỗng = dùng slug của ebook, để không phải khai lại cho mọi truyện.
        slug=str(reader_raw.get("slug", defaults_r.slug)).strip() or novel.slug,
        free_chapters=max(0, int(reader_raw.get("free_chapters", defaults_r.free_chapters))),
        published=bool(reader_raw.get("published", defaults_r.published)),
    )
    if reader.url and not reader.url.startswith(("http://", "https://")):
        warnings.append(
            f"reader.url={reader.url!r} thiếu scheme http(s):// — đẩy lên Reader sẽ lỗi."
        )
    if reader.service_key and not reader.url:
        warnings.append(
            "reader.service_key đã điền nhưng reader.url trống — đẩy lên Reader sẽ bị bỏ qua."
        )

    api_raw = _as_dict(raw.get("api"))
    origins_raw = api_raw.get("cors_origins")
    cors_origins = (
        [str(o).strip() for o in origins_raw if str(o).strip()]
        if isinstance(origins_raw, list)
        else []
    )
    api = ApiConfig(
        token=str(api_raw.get("token", "")).strip(),
        cors_origins=cors_origins,
        # Mặc định BẬT: DB đã có từ trước schema v8 không có khoá này, mà
        # hành vi mong muốn cho người dùng sẵn có là catalog tự cập nhật.
        auto_build=bool(api_raw.get("auto_build", True)),
    )

    return Config(novel=novel, crawl=crawl, translate=translate, ai=ai, output=output, queue=queue, reader=reader, api=api, source=source_name, warnings=warnings)
