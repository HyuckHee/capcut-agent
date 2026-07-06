import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""올빼미 59초 쇼츠 spec — 1분 초과+Content ID 차단 회피용 초압축 컷.

사용: python build_owl_59.py <owl.mp4(ASCII경로)> <spec.json 출력>
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

VIDEO = sys.argv[1]
SPEC_OUT = sys.argv[2]

OUTPUT = r"C:\Users\leehh\OneDrive\문서\캡컷에이전트\완성영상\올빼미_세자독살_쇼츠_59초.mp4"
VOICE = "tc_68257f68bc6e3c161ab5078d"

# 핵심 비트만 (원본 시각): 훅 → 복선 → 반전 → 독살 → 참기 → 연기 → 마무리
SEGS = [
    (1.0, 5.0),       # 궁녀 대사 (훅)
    (8.0, 15.0),      # 이동 + 맹인 소개 나레이션
    (104.0, 110.0),   # 이상함
    (125.2, 133.5),   # 불꺼짐 + 눈뜸 (반전)
    (147.0, 154.5),   # 독살 목격
    (168.5, 178.5),   # 의원이 주인공을 의심하는 응시 대치 (원본 2:48~)
    (199.0, 202.3),   # 참기 (시바)
    (234.0, 240.0),   # 맹인 연기
    (258.0, 265.3),   # 의원 마무리 (독살을 끝냅니다에서 종료)
]
kept = sum(e - s for s, e in SEGS)
print(f"59초판 길이: {kept:.1f}s (쇼츠 차단 한도 60s)")


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
    (107.0, "근데 뭔가, 좀 이상하죠?"),
    (126.0, "불이 꺼지는 순간, 눈을 뜹니다. 사실 이 남자, 어두울 때만 보이는 주맹증이었거든요."),
    (147.5, "그리고 그 눈에 들어오는 건, 치료가 아니라 독살. 다 봐버린 겁니다.",
     "그리고 그 눈에 들어오는 건,|치료가 아니라 독살|다 봐버린 겁니다"),
    (171.0, "의원이 눈치챈 걸까요? 숨소리조차 낼 수 없는 순간입니다."),
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
    print(f"  {d['at']:5.1f}s  {d['text'][:28]}…")

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
