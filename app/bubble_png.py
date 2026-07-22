"""이모지 포함 말풍선을 PNG로 렌더 — ffmpeg drawtext는 한 폰트만 쓰므로
주아체(이모지 글리프 없음)로는 이모지가 네모로 깨진다. 텍스트는 주아체,
이모지는 Segoe UI Emoji(컬러)로 한 이미지에 그려 overlay로 얹는다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUA = ROOT / "library" / "fonts" / "Jua-Regular.ttf"
EMOJI_FONT = (Path("C:/Windows/Fonts/seguiemj.ttf") if os.name == "nt"
              else Path("/System/Library/Fonts/Apple Color Emoji.ttc"))

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
    text = text.replace("…", "").replace("·", "")  # 주아체 미지원 글리프
    return render_text_png(text, out_path, font_path=JUA, fontsize=fontsize, stroke=stroke)


def render_text_png(text: str, out_path: str | Path, font_path: str | Path | None = None,
                    fontsize: int = 60, stroke: int = 7, box: bool = False,
                    color: str = "white") -> tuple[int, int]:
    """이모지 섞인 텍스트 한 줄을 투명 PNG로 — drawtext가 못 그리는 이모지용 범용 렌더.

    box=True면 반투명 검은 박스(풀스크린 제목 가독성용)를 깔아준다. (너비, 높이) 반환.
    """
    from PIL import Image, ImageDraw, ImageFont

    runs: list[list] = []  # [is_emoji, 문자열]
    for ch in text:
        e = _is_emoji(ch)
        if runs and runs[-1][0] == e:
            runs[-1][1] += ch
        else:
            runs.append([e, ch])

    jua = ImageFont.truetype(str(font_path or JUA), fontsize)
    emj, emj_scale = _load_emoji(ImageFont, fontsize)
    if emj is None:
        emj, emj_scale = jua, 1.0
    asc_j, desc_j = jua.getmetrics()
    asc_e, desc_e = (int(m * emj_scale) for m in emj.getmetrics())
    ascent, descent = max(asc_j, asc_e), max(desc_j, desc_e)

    pad = stroke + (20 if box else 4)  # 박스 모드는 drawtext boxborderw=16과 비슷한 여백
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    total_w = sum(probe.textlength(s, font=emj) * emj_scale if e
                  else probe.textlength(s, font=jua) for e, s in runs)
    W = int(total_w) + pad * 2
    H = ascent + descent + pad * 2

    img = Image.new("RGBA", (max(W, 4), H), (0, 0, 0, 128) if box else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x, base = float(pad), pad + ascent
    for e, s in runs:
        if e:
            x += _draw_emoji(Image, ImageDraw, img, s, emj, emj_scale, x, base)
        else:
            d.text((x, base), s, font=jua, fill=color, anchor="ls",
                   stroke_width=stroke, stroke_fill="black")
            x += d.textlength(s, font=jua)
    img.save(out_path)
    return img.size


def _load_emoji(ImageFont, fontsize: int):
    """이모지 폰트 로드 → (폰트, 배율). 맥 애플 이모지는 비트맵 고정 크기(160 등)만
    지원하므로 큰 크기로 로드하고 그릴 때 fontsize로 축소한다."""
    if not EMOJI_FONT.exists():
        return None, 1.0
    try:
        return ImageFont.truetype(str(EMOJI_FONT), fontsize), 1.0
    except OSError:
        for strike in (160, 137, 96, 64, 32):
            try:
                return ImageFont.truetype(str(EMOJI_FONT), strike), fontsize / strike
            except OSError:
                continue
    return None, 1.0


def _draw_emoji(Image, ImageDraw, img, s: str, emj, scale: float,
                x: float, base: int) -> float:
    """이모지 런을 그리고 진행 폭을 반환. 배율이 있으면 별도 캔버스에 그려 축소 합성."""
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    w = probe.textlength(s, font=emj)
    if scale == 1.0:
        ImageDraw.Draw(img).text((x, base), s, font=emj, embedded_color=True, anchor="ls")
        return w
    asc, desc = emj.getmetrics()
    tmp = Image.new("RGBA", (max(int(w), 1), asc + desc), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, asc), s, font=emj, embedded_color=True, anchor="ls")
    tw, th = max(int(w * scale), 1), max(int((asc + desc) * scale), 1)
    tmp = tmp.resize((tw, th), Image.LANCZOS)
    img.alpha_composite(tmp, (int(x), base - int(asc * scale)))
    return w * scale
