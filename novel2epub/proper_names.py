"""Dò tên riêng từ raw + hàng chờ duyệt glossary — logic thuần, không I/O HTTP.

Tách từ `app/routes/glossary.py` để Assistant Panel (job fill-context) và các
route cùng tái dùng một recognizer duy nhất. Kết quả luôn phải qua hàng chờ
duyệt (`glossary_pending`) trước khi thành glossary.
"""
from __future__ import annotations

import re
from collections import Counter

_SURNAME = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊於惠甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
_NAME_CONTEXT = re.compile(r"(?:说道|问道|笑道|喝道|叫道|看着|望向|对|向|与|跟|被|将|让)([\u3400-\u9fff]{2,4})")
_HAN_TOKEN = re.compile(r"[\u3400-\u9fff]{2,4}")
_NAME_STOP = {"什么", "怎么", "这个", "那个", "自己", "他们", "我们", "你们", "现在", "时候", "因为", "所以", "但是", "如果", "没有", "一个", "已经", "可以", "知道", "说道", "问道", "看着", "起来", "出来", "进去", "这里", "那里"}


def extract_proper_name_candidates(texts: list[tuple[int, str]], *, min_frequency: int = 2, max_candidates: int = 100) -> list[dict]:
    """Dò ứng viên tên người từ raw bằng surname + ngữ cảnh hội thoại.

    Đây là recognizer bảo thủ, không khẳng định entity: kết quả luôn phải qua
    hàng chờ duyệt trước khi thành glossary.
    """
    counts: Counter[str] = Counter()
    contexts: dict[str, str] = {}
    chapters: dict[str, int] = {}
    contextual: Counter[str] = Counter()
    for chapter_index, text in texts:
        for match in _HAN_TOKEN.finditer(text):
            token = match.group(0)
            if token in _NAME_STOP or token[0] not in _SURNAME:
                continue
            counts[token] += 1
            chapters.setdefault(token, chapter_index)
            contexts.setdefault(token, text[max(0, match.start() - 18): match.end() + 18].replace("\n", " "))
        for token in _NAME_CONTEXT.findall(text):
            if token not in _NAME_STOP:
                contextual[token] += 1
                counts[token] += 1
                chapters.setdefault(token, chapter_index)
    rows = []
    for source, frequency in counts.most_common():
        if frequency < min_frequency:
            continue
        context_hits = contextual[source]
        confidence = min(0.98, 0.45 + min(frequency, 10) * 0.035 + min(context_hits, 3) * 0.1)
        rows.append({
            "source": source,
            "frequency": frequency,
            "confidence": round(confidence, 2),
            "chapter_index": chapters[source],
            "context": contexts.get(source, ""),
        })
        if len(rows) >= max_candidates:
            break
    return rows


def normalize_pending_queue(raw) -> list[dict]:
    """Normalize snapshot hàng chờ mà không đọc DB thêm lần nữa."""
    from .storage import normalize_glossary_pending

    return normalize_glossary_pending(raw)


def read_pending_queue(storage) -> list[dict]:
    """Hàng chờ duyệt thay đổi auto-glossary (extra json `glossary_pending`),
    đã migrate schema replacement + normalize."""
    storage.migrate_glossary_queue()
    return normalize_pending_queue(storage.read_extra_json("glossary_pending"))


def queue_proper_name_candidates(storage, candidates: list[dict]) -> dict:
    """Xếp ứng viên tên riêng vào hàng chờ duyệt, bỏ qua mục glossary đã có và
    source đã chờ. Không bao giờ ghi trực tiếp vào glossary chuẩn.

    Trả `{"scanned": n, "detected": n, "queued": n, "skipped_existing": n}`.
    """
    existing = {source for source, _t, _n in storage.read_glossary_entries_merged()}
    pending_before = read_pending_queue(storage)
    pending_sources = {row["source"] for row in pending_before}
    additions: list[dict] = []
    skipped_existing = 0
    for row in candidates:
        source = row["source"]
        if source in existing or source in pending_sources:
            skipped_existing += 1
            continue
        additions.append({
            "source": source,
            "existing_target": "",
            "target": source,
            "chapter_index": row["chapter_index"],
            "note": f"Raw NER · tần suất {row['frequency']} · tin cậy {row['confidence']:.0%} · {row['context']}",
        })

    def _merge(current):
        pending = normalize_pending_queue(current)
        seen = {row["source"] for row in pending}
        return pending + [row for row in additions if row["source"] not in seen and row["source"] not in existing]

    merged = storage.update_extra_json("glossary_pending", _merge)
    return {
        "detected": len(candidates),
        "queued": len(merged) - len(pending_before),
        "skipped_existing": skipped_existing,
    }
