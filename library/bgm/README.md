# BGM 라이브러리 분류

곡별 무드·용도 카탈로그. 기계가 읽는 원본은 `catalog.json` (웹 UI BGM 목록 라벨에도 표시됨).
새 곡을 넣으면 catalog.json에 항목을 추가할 것 — 없으면 UI에 파일명만 뜬다.
모든 곡은 mean_volume ≈ -18dB로 레벨 정규화되어 있음 (새 곡 추가 시 동일하게 맞출 것 — spec `vol` 감각이 곡마다 달라지지 않게).

## 컨셉별 추천

| 컨셉 | 1순위 | 대안 |
|---|---|---|
| 장난·놀이·소동 쇼츠 | ukulele_bounce | about_that_oldie |
| 코믹 상황극 (컵도둑류) | about_that_oldie | ukulele_bounce |
| 몰래·살금살금·브이로그 | pizzicato_play | a_stroll |
| 잔잔한 일상·산책 롱폼 | a_stroll | pizzicato_play |
| 아기 강아지 귀여움·장난감 | toy_piano | ukulele_bounce |
| 자는 장면·자장가 엔딩 | cute_musicbox ⚠ | toy_piano |
| 회상·감동·회복 스토리 | shattered_paths | a_stroll |
| 신나는 모험·설렘 오프닝 | second_run ⚠ | motivity ⚠ |
| 활발한 뛰놀기·나들이 | motivity ⚠ | ukulele_bounce |
| 포근한 하루 마무리·엔딩 | good_evening_narvik ⚠ | a_stroll |

## 곡별 상세

| 곡 | 무드 | 길이 | 메모 |
|---|---|---|---|
| ukulele_bounce | 경쾌·통통 | 45s | 짧은 코믹 컷 기본값 |
| pizzicato_play | 장난기·살금살금 | 45s | 3일차 브이로그 확정 곡 |
| cute_musicbox | 오르골·자장가 | 45s | ⚠ 발성(250-3000Hz)과 동일 음역 — 발성 있는 소스엔 bgm.duck 필수 |
| about_that_oldie | 레트로 스윙 | 1:54 | 노즈워크 컵도둑 사용 곡. 곡 자체 엔딩 있음 (114s 이하 영상이면 자연 마무리 활용 가능) |
| a_stroll | 여유·산책 재즈 | 3:04 | 롱폼용. 나레이션과 안 부딪히는 차분한 그루브 |
| shattered_paths | 감성 피아노 | 2:58 | 뭉클한 스토리·시네마틱 |
| toy_piano | 아기자기·토이 | 1:39 | 앙증맞음 강조 |
| second_run | 경쾌·설렘 | 1:57 | 테일즈위버 OST ⚠ |
| motivity | 활기·상쾌 | 3:43 | 테일즈위버 OST ⚠. 긴 곡이라 롱폼에도 사용 가능 |
| good_evening_narvik | 따뜻·저녁 무드 | 2:56 | 테일즈위버 OST ⚠. 잔잔해서 나레이션과 잘 어울림 |

## ⚠ 테일즈위버 OST 3곡 (second_run, motivity, good_evening_narvik)
공식 공지 기준 **비영리 목적 사용만 허용** (팬메이드 영상 OK, 영리 불가). 채널 수익화 시점에는 이 3곡 쓴 영상의 BGM 교체 재렌더 필요 — spec JSON 보관 필수. Content ID 자동 매칭 가능성 있음(수익귀속형).
원본 mp3 3개(`Second Run.mp3` 등)는 재정규화 대비 보관.

## 사용법
- render_cute: `--bgm 이름` (예: `--bgm about_that_oldie`)
- render_cinema spec: `"bgm": {"path": "<library/bgm/이름.wav 절대경로>", "vol": 0.08}` (0.08 = 표준 100%)
- 웹 UI: BGM 드롭다운에 `이름 — 무드` 형식으로 표시
