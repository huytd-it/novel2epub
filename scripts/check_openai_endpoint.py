"""Kiểm tra một endpoint OpenAI-Compatible bằng chính code mà app dùng.

Hữu ích khi tự host model (vd notebook `notebooks/novel2epub_zhvi_server.ipynb`
chạy trên Colab/Kaggle): xác nhận tunnel còn sống, `GET /models` trả đúng danh
sách cho dropdown Settings, và `POST /chat/completions` trả nội dung sạch —
không `<think>`, không fence Markdown, không sót chữ Hán.

Dùng `novel2epub.openai_client` chứ không phải curl, để đo đúng hành vi thật:
stream SSE, một message `user`, không có `max_tokens`/`extra_body`.

Chạy:
    python scripts/check_openai_endpoint.py --base-url https://xxx.trycloudflare.com/v1 --api-key n2e-...
    python scripts/check_openai_endpoint.py --base-url ... --api-key ... --model novel2epub-zhvi --repeat 3
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel2epub.config import OpenAIConfig  # noqa: E402
from novel2epub.openai_client import list_models, run_chat  # noqa: E402

HAN_RE = re.compile(r"[一-鿿]")

SAMPLE_ZH = (
    "夜色如墨，青云宗后山的古松在寒风中低吟。林逸盘膝坐在断崖边，掌心翻转，"
    "一缕微弱的灵气缓缓凝聚。「师兄，你当真要去闯那试炼塔？」"
    "少女的声音自身后传来，带着掩不住的担忧。"
)

PROMPT = (
    "Dịch đoạn văn tiếng Trung sau sang tiếng Việt. Giữ nguyên cách xuống dòng, "
    "văn phong truyện tiên hiệp, không thêm lời dẫn, chỉ trả về bản dịch.\n\n{text}"
)


def _check_output(text: str) -> list[str]:
    problems = []
    if "<think>" in text or "</think>" in text:
        problems.append("còn thẻ <think> — bật shim trong notebook hoặc tắt thinking mode ở server")
    if text.lstrip().startswith("```"):
        problems.append("mở đầu bằng fence Markdown (translator tự bóc, nhưng nên chú ý)")
    han = HAN_RE.findall(text)
    if len(han) > 3:
        problems.append(f"còn {len(han)} ký tự Hán — cần bước Clear Hán hoặc đổi model")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True, help="vd https://xxx.trycloudflare.com/v1")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="", help="bỏ trống = lấy model đầu tiên từ /models")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--repeat", type=int, default=1, help="số lần gọi để xem độ ổn định/độ trễ")
    ap.add_argument("--text", default=SAMPLE_ZH, help="đoạn nguồn để dịch thử")
    args = ap.parse_args()

    print(f"GET {args.base_url.rstrip('/')}/models")
    try:
        models = list_models(args.base_url, args.api_key, timeout_seconds=30)
    except Exception as e:
        print(f"  LỖI: {e}")
        print("  → Kiểm tra base_url (phải kết thúc bằng /v1), api_key, và tunnel còn sống không.")
        return 1
    print(f"  → {len(models)} model: {', '.join(models) or '(rỗng)'}")

    model = args.model or (models[0] if models else "")
    if not model:
        print("  Không có model nào và cũng không truyền --model.")
        return 1

    cfg = OpenAIConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        model=model,
        timeout_seconds=args.timeout,
        temperature=args.temperature,
    )

    failures = 0
    for i in range(1, args.repeat + 1):
        print(f"\nPOST /chat/completions (model={model}, lần {i}/{args.repeat})")
        started = time.time()
        try:
            out = run_chat(cfg, PROMPT.format(text=args.text))
        except Exception as e:
            failures += 1
            print(f"  LỖI: {e}")
            continue
        elapsed = time.time() - started
        print("  " + out.strip().replace("\n", "\n  "))
        print(f"  [{len(out)} ký tự / {elapsed:.1f}s ≈ {len(out) / max(elapsed, 0.01):.0f} ký tự/s]")
        problems = _check_output(out)
        if problems:
            failures += 1
            for p in problems:
                print(f"  CẢNH BÁO: {p}")

    if failures:
        print(f"\n{failures}/{args.repeat} lần có vấn đề.")
        return 1
    print("\nEndpoint dùng được: dán base_url/api_key/model vào Cài đặt > Dịch API và AI biên tập.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
