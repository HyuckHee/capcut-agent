"""이모지 포함 말풍선을 PNG로 렌더 — ffmpeg drawtext는 한 폰트만 쓰므로
주아체(이모지 글리프 없음)로는 이모지가 네모로 깨진다. 텍스트는 주아체,
이모지는 Segoe UI Emoji(컬러)로 한 이미지에 그려 overlay로 얹는다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUA = ROOT / "library" / "fonts" / "Jua-Regular.ttf"
EMOJI_FONT = Path("C:/Windows/Fonts/seguiemj.ttf")

# 이모지·기호 판정 범위 (변형 선택자·ZWJ·국기 포함)
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
    (0x1F1E6, 0x1F1FF), (0xFE00, 0xFE0F), (0x200D, 0x200D),
    (0x2190, 0x21FF), (0x2934, 0x2935),
)


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _EMOJI_RANGES)


def has_emoji(text: str) -> bool:
    return any(_is_emoji(c) for c in text)


def render_bubble(text: str, out_path: str | Path, fontsize: int = 60,
                  stroke: int = 7) -> tuple[int, int]:
    """말풍선 한 줄을 투명 PNG로. (너비, 높이) 반환."""
    from PIL import Image, ImageDraw, ImageFont

    text = text.replace("…", "").replace("·", "")  # 주아체 미지원 글리프
    runs: list[list] = []  # [is_emoji, 문자열]
    for ch in text:
        e = _is_emoji(ch)
        if runs and runs[-1][0] == e:
            runs[-1][1] += ch
        else:
            runs.append([e, ch])

    jua = ImageFont.truetype(str(JUA), fontsize)
    emj = ImageFont.truetype(str(EMOJI_FONT), fontsize) if EMOJI_FONT.exists() else jua
    asc_j, desc_j = jua.getmetrics()
    asc_e, desc_e = emj.getmetrics()
    ascent, descent = max(asc_j, asc_e), max(desc_j, desc_e)

    pad = stroke + 4
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    total_w = sum(probe.textlength(s, font=(emj if e else jua)) for e, s in runs)
    W = int(total_w) + pad * 2
    H = ascent + descent + pad * 2

    img = Image.new("RGBA", (max(W, 4), H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x, base = float(pad), pad + ascent
    for e, s in runs:
        if e:
            d.text((x, base), s, font=emj, embedded_color=True, anchor="ls")
            x += d.textlength(s, font=emj)
        else:
            d.text((x, base), s, font=jua, fill="white", anchor="ls",
                   stroke_width=stroke, stroke_fill="black")
            x += d.textlength(s, font=jua)
    img.save(out_path)
    return img.size
