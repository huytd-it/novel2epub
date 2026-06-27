from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .text_preprocess import NORMALIZE_T2S, normalize_chinese_text

HONORIFIC_OFF = "off"
HONORIFIC_SAFE = "safe"
HONORIFIC_STRICT = "xianxia_strict"
HONORIFIC_MODES = {HONORIFIC_OFF, HONORIFIC_SAFE, HONORIFIC_STRICT}
KINSHIP_MODES = {"always", "classical_only"}
_BOUNDARY_CHARS = r"\wÀ-ỹ"

_RAW = {
    "哥们": {"hv": None}, "哥们儿": {"hv": None}, "哥儿们": {"hv": None},
    "大哥大": {"hv": None}, "弟媳": {"hv": None}, "弟妹": {"hv": None},
    "小姐": {"hv": None}, "大嫂": {"hv": None}, "嫂子": {"hv": None}, "嫂": {"hv": None},
    "我们": {"hv": None}, "咱们": {"hv": None}, "你们": {"hv": None},
    "他们": {"hv": None}, "她们": {"hv": None},
    "我校": {"hv": None}, "我司": {"hv": None}, "我国": {"hv": None},
    "我方": {"hv": None}, "我院": {"hv": None},
    "师兄": {"hv": "sư huynh", "drift": ["sư ca", "sư anh"], "tier": "kinship"},
    "师弟": {"hv": "sư đệ", "drift": ["sư em"], "tier": "kinship"},
    "师姐": {"hv": "sư tỷ", "drift": ["sư chị"], "tier": "kinship"},
    "师妹": {"hv": "sư muội", "drift": ["sư em"], "tier": "kinship"},
    "师叔": {"hv": "sư thúc", "drift": [], "tier": "kinship"},
    "师伯": {"hv": "sư bá", "drift": [], "tier": "kinship"},
    "师祖": {"hv": "sư tổ", "drift": [], "tier": "kinship"},
    "徒儿": {"hv": "đồ nhi", "drift": [], "tier": "kinship"},
    "姐妹": {"hv": "tỷ muội", "drift": ["chị em"], "tier": "kinship"},
    "兄弟": {"hv": "huynh đệ", "drift": ["anh em"], "tier": "kinship"},
    "兄妹": {"hv": "huynh muội", "drift": ["anh em"], "tier": "kinship"},
    "姐弟": {"hv": "tỷ đệ", "drift": ["chị em"], "tier": "kinship"},
    "师徒": {"hv": "sư đồ", "drift": [], "tier": "kinship"},
    "姐姐": {"hv": "tỷ tỷ", "drift": ["chị gái", "chị"], "tier": "kinship"},
    "妹妹": {"hv": "muội muội", "drift": ["em gái"], "tier": "kinship"},
    "哥哥": {"hv": "ca ca", "drift": ["anh trai", "anh"], "tier": "kinship"},
    "弟弟": {"hv": "đệ đệ", "drift": ["em trai"], "tier": "kinship"},
    "大哥": {"hv": "đại ca", "drift": ["anh cả", "anh lớn", "anh hai"], "tier": "kinship"},
    "公子": {"hv": "công tử", "drift": [], "tier": "kinship"},
    "姑娘": {"hv": "cô nương", "drift": [], "tier": "kinship"},
    "师尊": {"hv": "sư tôn", "drift": [], "tier": "kinship"},
    "师父": {"hv": "sư phụ", "drift": [], "tier": "kinship"},
    "前辈": {"hv": "tiền bối", "drift": [], "tier": "kinship"},
    "晚辈": {"hv": "vãn bối", "drift": [], "tier": "kinship"},
    "本座": {"hv": "bản tọa", "drift": [], "tier": "kinship"},
    "姐": {"hv": "tỷ", "drift": ["chị"], "tier": "kinship_single"},
    "妹": {"hv": "muội", "drift": [], "tier": "kinship_single"},
    "哥": {"hv": "ca", "drift": ["anh"], "tier": "kinship_single"},
    "弟": {"hv": "đệ", "drift": [], "tier": "kinship_single"},
    "你": {"hv": "ngươi", "drift": ["cậu", "bạn", "mày"], "tier": "pronoun"},
    "您": {"hv": "ngài", "drift": ["ông", "bác"], "tier": "pronoun"},
    "他": {"hv": "hắn", "drift": ["anh ấy", "anh ta", "cậu ấy", "cậu ta", "gã"], "tier": "pronoun"},
    "她": {"hv": "nàng", "drift": ["cô ấy", "cô ta", "ả"], "tier": "pronoun"},
    "我": {"hv": "ta", "drift": ["tôi", "tớ"], "tier": "pronoun"},
}

HONORIFIC_MAP: dict[str, dict] = {}
for _k, _v in _RAW.items():
    _e = dict(_v)
    if _e.get("drift"):
        _e["drift"] = sorted(_e["drift"], key=len, reverse=True)
    HONORIFIC_MAP[_k] = _e

_TERMS_BY_LEN = sorted(HONORIFIC_MAP.keys(), key=len, reverse=True)
WUXIA_SIGNALS = [
    "修士", "修真", "修仙", "元婴", "金丹", "筑基", "真君", "法宝", "丹药", "灵气",
    "仙人", "仙子", "剑修", "渡劫", "结丹", "化神", "真人", "道君", "宗门", "灵根",
    "本座", "贫道", "道友", "天劫", "神识", "真元", "灵石", "符箓", "阵法", "飞剑",
]
MODERN_SIGNALS = [
    "公司", "大学", "电话", "手机", "电脑", "网络", "汽车", "老板", "经理", "项目",
    "咖啡", "地铁", "飞机", "酒店", "警察", "医院", "护士", "短信", "微信", "视频",
    "直播", "电视", "银行", "信用卡", "互联网", "程序", "软件", "总裁", "董事长",
]


def genre_score(zh: str) -> tuple[int, int]:
    c = sum(1 for s in WUXIA_SIGNALS if s in zh)
    m = sum(1 for s in MODERN_SIGNALS if s in zh)
    return c, m


def is_classical(zh: str) -> bool:
    c, m = genre_score(zh)
    if m == 0:
        return c >= 1
    return c >= 2 and c > m


def longest_match_mentions(zh: str) -> list[str]:
    mentions: list[str] = []
    i = 0
    while i < len(zh):
        matched = ""
        for term in _TERMS_BY_LEN:
            if zh.startswith(term, i):
                matched = term
                break
        if matched:
            mentions.append(matched)
            i += len(matched)
        else:
            i += 1
    return mentions


def honorific_mode(mode: str | None) -> str:
    mode = (mode or HONORIFIC_OFF).strip().lower()
    return mode if mode in HONORIFIC_MODES else HONORIFIC_OFF


def _mode_to_flags(mode: str) -> tuple[bool, bool]:
    mode = honorific_mode(mode)
    if mode == HONORIFIC_SAFE:
        return True, False
    if mode == HONORIFIC_STRICT:
        return True, True
    return False, False


def normalize_honorifics(zh: str, vi: str, mode: str | None = None,
                         *, apply_kinship: bool | None = None,
                         apply_pronouns: bool | None = None,
                         kinship_mode: str = "always",
                         enable_single: bool = False,
                         classical_context: bool | None = None) -> str:
    if apply_kinship is None and apply_pronouns is None:
        apply_kinship, apply_pronouns = _mode_to_flags(mode)
    else:
        apply_kinship = bool(apply_kinship)
        apply_pronouns = bool(apply_pronouns)

    if (not apply_kinship and not apply_pronouns) or not vi or not zh:
        return vi
    vi = unicodedata.normalize("NFC", vi)
    zh = unicodedata.normalize("NFC", normalize_chinese_text(zh, NORMALIZE_T2S))
    mentions = longest_match_mentions(zh)
    if not mentions:
        return vi
    classical = bool(classical_context) if classical_context is not None else is_classical(zh)
    for term in mentions:
        entry = HONORIFIC_MAP.get(term) or {}
        hv = entry.get("hv")
        if hv is None:
            continue
        if (entry["tier"] == "pronoun" and (not apply_pronouns or not classical)):
            continue
        if entry["tier"] == "kinship_single" or (entry["tier"] == "kinship" and not apply_kinship):
            continue
        drift = entry.get("drift", [])
        if not drift:
            continue
        for v in drift:
            vi = re.sub(
                rf"(?<![{_BOUNDARY_CHARS}]){re.escape(v)}(?![{_BOUNDARY_CHARS}])",
                hv,
                vi,
                flags=re.IGNORECASE,
                count=1,
            )
    return vi


normalize = normalize_honorifics


def honorific_message(mode: str | None) -> str:
    mode = honorific_mode(mode)
    if mode == HONORIFIC_OFF:
        return "Giữ nguyên xưng hô theo bản dịch."
    if mode == HONORIFIC_SAFE:
        return "Đã chuẩn hóa xưng hô thân tộc sang Hán-Việt (tỷ/muội/ca ca...)."
    return "Đã chuẩn hóa xưng hô Hán-Việt gồm cả đại từ (ngươi/hắn/nàng/ta)."
