# 진행 현황 (2026-02-25)

## 완료
- OpenCode 플러그인 + 훅 연동 완료.
- OpenRouter 무료 모델 기준 E2E 실행 검증 완료.
- 턴 메타데이터에 메시지 단위 이력 저장 기능 추가.

## 검증
- 훅/플러그인 문법 검사 통과.
- Langfuse에서 `session.created` / `turn` / `session.idle` 트레이스 확인.
- 메타데이터(`session_id`, `user_id`, `hostname`, `message_events`) 확인 완료.

## 다음
- 필요 시 스트리밍 디버깅용 delta-level 캡처 모드 옵션 추가.
