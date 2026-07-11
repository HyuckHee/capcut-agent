# 에이전트 분업 기본틀 (템플릿)

Claude Code 서브에이전트로 영상 제작을 역할별로 분업하기 위한 **기본틀**입니다.
실제 사용하려면 이 폴더의 파일들을 `.claude/agents/`로 복사한 뒤, `<로컬 설정>` 표시 부분을
각자의 채널 노하우(확정 스타일, 음성 캐스팅 등)로 채우세요. `.claude/`는 gitignore 대상이라
개인 노하우는 저장소에 올라가지 않습니다.

## 구성
- `chief-director.md` — 총괄 감독: 포맷 결정, 작업지시서, 최종 검수 게이트
- `story-planner.md` — 줄거리: 소스 전수 프레임 확인 → 스토리 + 세그먼트 설계
- `video-editor.md` — 영상편집: 마스터/최종 렌더, 오디오 믹스, 렌더 후 검증
- `narration-director.md` — 나레이션: 대본·음성 캐스팅·배치 설계
- `subtitle-designer.md` — 자막: 자막/라벨/타이틀 필드 설계 + 화면 일치 검증

## 협업 규약
- 순서: chief-director(계획) → story-planner → video-editor(마스터) → [narration ‖ subtitle 병렬] → video-editor(최종 렌더) → chief-director(검수)
- 중간 산출물은 `logs/jobs/<ascii-프로젝트명>/`에 파일로 주고받음 (한글 경로 금지):
  `plan.md`, `story.md`, `segments.json`, `master.mp4`, `timeline.md`, `narration.json`, `subtitles.json`
- 나레이션·자막의 시각은 **마스터(완성) 타임라인 기준** — 세그먼트 확정 후에만 착수
