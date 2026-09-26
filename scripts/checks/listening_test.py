"""
The Egyptian side-by-side: Lahgtna OmniVoice v2 against Egyptian v3, blind.

    make listening-test V2_URL=http://gpu:8440 V3_URL=http://gpu:8441

where V3_URL is a second tts service started with TTS_USE_EGYPTIAN_MODEL=true.
Writes listening-test/page.html (one self-contained page: each sentence
twice, as A and B in random order, and a button that saves your choices)
and listening-test/key.json (which of A and B was v3; keep it from the
listeners). Then `python -m scripts.checks.listening_test score choices.json`
says whether v3 won.
"""

import argparse
import asyncio
import base64
import html
import json
import random
from pathlib import Path

from nafas_conversation.logic.speech import speakable
from nafas_core.interfaces.tts.http import HttpTTS

SENTENCES = [
    "أهلاً بيك، أقدر أساعدك تحجز معاد مع الدكتور.",
    "تمام، حجزتلك يوم الأربعاء الساعة ٥:٤٠ م. أكّد خلال ١٠ دقايق.",
    "للأسف الساعة دي محجوزة، في معاد الساعة ٦:٢٠ م أو ٧ م، تحب أنهي؟",
    "العيادة في المعادي، شارع ٩، الدور التالت.",
    "تم إلغاء المعاد بتاعك. تحب نحجز يوم تاني؟",
    "مفيش مواعيد فاضية بكرة، بس بعد بكرة في الساعة ٤ م.",
    "تمام، هبعتلك تذكير قبل المعاد بساعة.",
    "ممكن تقولي سبب الزيارة باختصار؟",
]
OUT = Path("listening-test")


def page(pairs: list[dict]) -> str:
    rows = []
    for i, pair in enumerate(pairs):
        players = "".join(
            f'<div><b>{side}</b> <audio controls src="data:audio/wav;base64,{pair[side]}"></audio></div>' for side in "AB"
        )
        choices = "".join(
            f'<label><input type="radio" name="q{i}" value="{v}"> {label}</label> '
            for v, label in (("A", "A أفضل"), ("B", "B أفضل"), ("same", "زي بعض"))
        )
        rows.append(f"<section><p>{html.escape(pair['text'])}</p>{players}<p>{choices}</p></section>")
    return f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8">
<title>اختبار الاستماع</title>
<style>
body{{font-family:system-ui;max-width:760px;margin:24px auto;padding:0 16px}}
section{{border-bottom:1px solid #ddd;padding:12px 0}}
</style>
<h1>أي صوت أوضح وأطبع؟</h1><p>اسمع A و B لكل جملة واختار. في الآخر احفظ النتيجة وابعتها.</p>
{"".join(rows)}
<button id="save">احفظ النتيجة</button>
<script>
document.getElementById("save").onclick = () => {{
  const answers = [...document.querySelectorAll("section")].map((_, i) =>
    (document.querySelector(`input[name=q${{i}}]:checked`) || {{}}).value || null);
  const blob = new Blob([JSON.stringify({{answers}})], {{type: "application/json"}});
  const link = Object.assign(document.createElement("a"), {{href: URL.createObjectURL(blob), download: "choices.json"}});
  link.click();
}};
</script></html>"""


def score(key: list[str], answers: list[str | None]) -> dict:
    """Wins per model across the pairs; `key[i]` is the side that was v3."""
    tally = {"v3": 0, "v2": 0, "same": 0, "unanswered": 0}
    for v3_side, answer in zip(key, answers, strict=True):
        if answer is None:
            tally["unanswered"] += 1
        elif answer == "same":
            tally["same"] += 1
        else:
            tally["v3" if answer == v3_side else "v2"] += 1
    tally["decision"] = "use v3 for Egyptian" if tally["v3"] > tally["v2"] else "keep v2"
    return tally


async def build(v2_url: str, v3_url: str, voice: str) -> None:
    v2, v3 = HttpTTS(v2_url), HttpTTS(v3_url)
    pairs, key = [], []
    for sentence in SENTENCES:
        text = speakable(sentence, "eg")
        a2 = base64.b64encode((await v2.speak(text, "eg", voice)).audio).decode()
        a3 = base64.b64encode((await v3.speak(text, "eg", voice)).audio).decode()
        v3_side = random.choice("AB")
        pairs.append({"text": sentence, "A": a3 if v3_side == "A" else a2, "B": a2 if v3_side == "A" else a3})
        key.append(v3_side)
    OUT.mkdir(exist_ok=True)
    (OUT / "page.html").write_text(page(pairs), encoding="utf-8")
    (OUT / "key.json").write_text(json.dumps(key), encoding="utf-8")
    print(f"{OUT / 'page.html'} for the listeners; keep {OUT / 'key.json'} to yourself")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build")
    make.add_argument("--v2-url", required=True)
    make.add_argument("--v3-url", required=True)
    make.add_argument("--voice", choices=["female", "male"], default="female")
    judged = commands.add_parser("score")
    judged.add_argument("choices", type=Path)
    judged.add_argument("--key", type=Path, default=OUT / "key.json")
    args = parser.parse_args()

    if args.command == "build":
        asyncio.run(build(args.v2_url, args.v3_url, args.voice))
    else:
        key = json.loads(args.key.read_text())
        answers = json.loads(args.choices.read_text())["answers"]
        print(json.dumps(score(key, answers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
