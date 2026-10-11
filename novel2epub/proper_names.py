"""Dò tên riêng từ raw + hàng chờ duyệt glossary — logic thuần, không I/O HTTP.

Tách từ `app/routes/glossary.py` để Assistant Panel (job fill-context) và các
route cùng tái dùng một recognizer duy nhất. Kết quả luôn phải qua hàng chờ
duyệt (`glossary_pending`) trước khi thành glossary.
"""
from __future__ import annotations

import re
from collections import Counter

from .han_cleanup import count_han

_SURNAME = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊於惠甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
_NAME_CONTEXT = re.compile(r"(?:说道|问道|笑道|喝道|叫道|看着|望向|对|向|与|跟|被|将|让)([\u3400-\u9fff]{2,4})")
_HAN_TOKEN = re.compile(r"[\u3400-\u9fff]{2,4}")
_NAME_STOP = {"什么", "怎么", "这个", "那个", "自己", "他们", "我们", "你们", "现在", "时候", "因为", "所以", "但是", "如果", "没有", "一个", "已经", "可以", "知道", "说道", "问道", "看着", "起来", "出来", "进去", "这里", "那里"}

# Tên phiên âm nước ngoài chỉ dùng một tập chữ hẹp (bảng phiên âm Tân Hoa Xã),
# nên một chuỗi nằm trọn trong tập đó gần như chắc là tên phiên âm.
# Chữ hay dùng để phiên âm tên nước ngoài.
_TRANSLIT_CHARS = set(
    "阿埃艾爱安昂奥巴白拜班邦保鲍贝本比彼毕宾波伯博布蔡策查柴昌彻楚茨达代戴丹当道德登邓迪蒂丁东杜敦多"
    "厄恩尔法凡范菲费芬丰冯弗福夫盖甘冈高戈哥格葛根贡古瓜圭哈海汉豪赫黑亨洪胡华怀惠霍基吉季加佳贾简杰捷"
    "金津京卡开凯坎康考柯科可克肯孔库夸奎拉莱赖兰朗劳勒雷蕾累里丽莉利立力黎理李林琳龙隆卢鲁露路伦罗洛吕"
    "略马玛迈麦曼芒毛梅美门蒙孟米密蜜敏明缪莫默姆穆娜纳奈南内妮尼宁纽农努诺欧帕派潘庞佩彭皮平珀普奇齐恰"
    "钱强乔切钦琴丘琼曲让热若萨塞赛桑瑟森沙莎山尚绍舍申圣施什史士舒斯丝思松苏索塔泰坦汤唐陶特腾提田铁廷"
    "通图土托瓦娃万旺威薇韦维伟魏温文翁沃乌伍武西希锡席夏肖谢辛欣兴休修雪逊雅亚扬尧耶叶伊依易因英尤于雨"
    "约泽曾扎詹珍芝朱卓兹佐姬妲娅琪黛茜芙珊"
)
# Chữ gần như chỉ gặp trong tên phiên âm, hiếm trong tên/thuật ngữ Trung Quốc.
_TRANSLIT_STRONG = set("斯尔克特姆兹茨夫伦顿森逊洛莱蕾薇菲芙恩奥埃厄欧乌瓦佩帕珀普赫萨塞瑟舍勒迪蒂娅")
# Chữ phiên âm nhưng cũng hay có trong tên nữ Trung Quốc (李丽, 王琳): chỉ tính
# khi source không mở đầu bằng họ Trung Quốc.
_TRANSLIT_SOFT = set("丽琳娜莉妮亚莎")
_NAME_SEPARATORS = "·•・‧-－ "
_TRANSLIT_RUN = re.compile(
    "[{c}]{{2,8}}(?:[·•・‧][{c}]{{1,8}})*".format(c="".join(sorted(_TRANSLIT_CHARS)))
)


def is_transliterated_name(source: str) -> bool:
    """`source` trông như tên nước ngoài phiên âm bằng chữ Hán."""
    source = (source or "").strip()
    core = "".join(ch for ch in source if ch not in _NAME_SEPARATORS)
    if len(core) < 2 or count_han(core) != len(core):
        return False
    if any(sep in source for sep in "·•・‧"):
        return True
    if not set(core) <= _TRANSLIT_CHARS:
        return False
    if set(core) & _TRANSLIT_STRONG:
        return True
    return bool(set(core) & _TRANSLIT_SOFT) and core[0] not in _SURNAME


def extract_proper_name_candidates(texts: list[tuple[int, str]], *, min_frequency: int = 2, max_candidates: int = 100) -> list[dict]:
    """Dò ứng viên tên người từ raw bằng surname + ngữ cảnh hội thoại, cộng
    thêm tên nước ngoài phiên âm (chuỗi nằm trọn trong bảng chữ phiên âm).

    Mỗi ứng viên có `kind`: `translit` (tên phiên âm) hoặc `cn_name`.

    Đây là recognizer bảo thủ, không khẳng định entity: kết quả luôn phải qua
    hàng chờ duyệt trước khi thành glossary.
    """
    counts: Counter[str] = Counter()
    contexts: dict[str, str] = {}
    chapters: dict[str, int] = {}
    contextual: Counter[str] = Counter()
    translit: Counter[str] = Counter()
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
        for match in _TRANSLIT_RUN.finditer(text):
            token = match.group(0)
            if token in _NAME_STOP or not is_transliterated_name(token):
                continue
            translit[token] += 1
            chapters.setdefault(token, chapter_index)
            contexts.setdefault(token, text[max(0, match.start() - 18): match.end() + 18].replace("\n", " "))
    # Hai cách quét có thể cùng đếm một tên: lấy số lớn hơn, không cộng dồn.
    for token, frequency in translit.items():
        counts[token] = max(counts[token], frequency)
    rows = []
    for source, frequency in counts.most_common():
        if frequency < min_frequency:
            continue
        context_hits = contextual[source]
        confidence = min(0.98, 0.45 + min(frequency, 10) * 0.035 + min(context_hits, 3) * 0.1)
        rows.append({
            "source": source,
            "kind": "translit" if is_transliterated_name(source) else "cn_name",
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
