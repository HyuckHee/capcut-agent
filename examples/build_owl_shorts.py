import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""올빼미 쇼츠판(3분 이내) spec 생성 — 스토리 비트 유지, 비트 사이 정적 압축.

사용: python build_owl_shorts.py <owl.mp4(ASCII경로)> <spec.json 출력>
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

VIDEO = sys.argv[1]
SPEC_OUT = sys.argv[2]

OUTPUT = r"C:\Users\leehh\OneDrive\문서\캡컷에이전트\완성영상\올빼미_세자독살_쇼츠.mp4"
VOICE = "tc_68257f68bc6e3c161ab5078d"

# 쇼츠용 보존 구간 (원본 시각) — 나레이션/대사/반전 비트 전부 포함, 정적 압축
SEGS = [
    (0.0, 33.0),      # 오프닝 대사 + 준비 지시
    (44.0, 58.0),     # 치료 (명의 나레이션)
    (100.0, 131.0),   # 이상함 → 불꺼짐 → 눈뜸 (반전)
    (135.3, 168.0),   # 독살 목격 + 깜짝
    (192.0, 202.3),   # 시바 참기
    (220.7, 227.3),   # 긴장 대치
    (230.2, 247.9),   # 맹인 연기
    (258.0, 271.0),   # 마무리 + "안심하셔도 돼요"
]
kept = sum(e - s for s, e in SEGS)
print(f"쇼츠판 길이: {kept:.1f}s (쇼츠 한도 180s)")


def to_tl(src_t: float) -> float:
    cursor = 0.0
    for s, e in SEGS:
        if src_t < s:
            return cursor
        if src_t <= e:
            return cursor + src_t - s
        cursor += e - s
    return cursor


NARRS_SRC = [
    (8.5, "세자가 쓰러졌어요. 그런데 살리러 온 침술사, 앞이 안 보이는 맹인입니다."),
    (48.0, "누가 봐도, 세자를 살리려 밤새 애쓰는 명의의 모습이죠."),
    (107.0, "근데 뭔가, 좀 이상하죠?"),
    (126.0, "불이 꺼지는 순간, 눈을 뜹니다. 사실 이 남자, 어두울 때만 보이는 주맹증이었거든요."),
    (147.5, "그리고 그 눈에 들어오는 건, 치료가 아니라 독살. 다 봐버린 겁니다.",
     "그리고 그 눈에 들어오는 건,|치료가 아니라 독살|다 봐버린 겁니다"),
    (162.0, "아! 깜짝이야!", "아 깜짝이야"),
    (200.0, "와, 시바, 이걸 어떻게 참았냐.",
     "와 tlqkf 이걸 어떻게 참았냐"),
    (236.3, "미친 맹인 연기로, 의심을 벗어난 주인공.",
     "미친 맹인 연기로 의심을 벗어난 주인공"),
    (258.5, "그리고 의원은 아무 일 없었다는 듯, 치료를, 아니 독살을 끝냅니다.",
     "그리고 의원은 아무 일 없었다는 듯|치료를, 아니 독살을 끝냅니다"),
]

SUBS_SRC = [
    (1.3, 3.0, "세자 저하께서 쓰러지셔서"),
    (3.0, 4.8, "정신을 차리지 못하십니다"),
    (22.3, 26.3, "청에서 가져온 상산이 있다 하셨지요?"),
    (26.3, 27.7, "어서 달여 오십시오"),
    (27.7, 28.6, "네, 알겠습니다"),
    (28.6, 30.3, "급히 열을 내려야 하니"),
    (30.3, 32.0, "자네는 명주천을 짜서 건네주게"),
    (32.0, 33.0, "이쪽에 있네"),
    (266.4, 268.2, "열이 많이 내렸습니다"),
    (268.8, 270.6, "이제 안심하셔도 돼요"),
]

narrs = []
for item in NARRS_SRC:
    d = {"at": round(to_tl(item[0]), 2), "text": item[1]}
    if len(item) > 2:
        d["caption"] = item[2]
    narrs.append(d)
subs = [[round(to_tl(a), 2), round(to_tl(b), 2), t] for a, b, t in SUBS_SRC]
print("나레이션 배치:")
for d in narrs:
    print(f"  {d['at']:6.1f}s  {d['text'][:28]}…")

spec = {
    "video": VIDEO,
    "output": OUTPUT,
    "crop": "1920:804:0:138",
    "title": "죽어가는 세자를 목격한|맹인 침술사",
    "logo": {"text": "올빼미", "sub": "The Night Owl · 2022"},
    "exp_color": "0xFFD400",
    "labels": [],
    "voice": VOICE,
    "narr_captions": True,
    "narr_warm": False,
    "keywords": [],
    "segs": [[round(s, 2), round(e, 2)] for s, e in SEGS],
    "subs": subs,
    "exps": [],
    "narrs": narrs,
}
Path(SPEC_OUT).write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"spec 저장: {SPEC_OUT}")
