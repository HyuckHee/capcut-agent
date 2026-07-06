# examples/

실제 콘텐츠 제작 세션에서 사용한 일회성 스크립트 아카이브입니다.
각 파일은 특정 영상(왕희 브이로그, 영화 <올빼미> 짤)의 spec 생성·분석에 쓰였으며,
파이프라인을 새 소재에 적용할 때의 **참고 레시피** 역할을 합니다.

| 파일 | 용도 |
|---|---|
| `build_owl_full.py` | 영화 클립 풀버전 spec 생성 — 무음 컷 + 나레이션/자막 타임라인 자동 매핑 |
| `build_owl_shorts.py` / `build_owl_59.py` | 쇼츠 컷 (스토리 비트 압축 / Content ID 60초 대응) |
| `analyze_owl.py` | 무음 임계값 비교 분석 |
| `prep_owl.py` / `prep_wanghee.py` | 한글 경로 → ASCII 복사 (Windows ffmpeg 인코딩 이슈 우회) |
| `gen_samples.py` | TTS 음성 비교 샘플 생성 |
| `export_video.py` / `probe_ui.py` | CapCut UI 자동화 내보내기 시도 (신버전에서 미지원 확인) |
| `verify_draft.py` | CapCut draft JSON 구조 검증 |
| `debug_ffmpeg.py` | ffmpeg 인코딩 이슈 디버깅 |

실행은 저장소 루트에서: `python examples/<스크립트>.py` (루트 sys.path 자동 추가됨)
