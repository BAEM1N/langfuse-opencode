# langfuse-opencode

[English](README.md) | [한국어](README.ko.md)

OpenCode 로컬 플러그인 훅을 사용해 OpenCode 이벤트를 [Langfuse](https://langfuse.com)로 전송하는 프로젝트입니다.
`event` 훅에서 Python 스크립트를 호출하고, assistant 메시지를 턴 단위 trace로 재구성합니다.

## 상태 (2026년 2월 25일)

- ✅ OpenCode + OpenRouter 무료 모델 기준 E2E 검증 완료
- ✅ `session.created` / `turn` / `session.idle` 트레이스가 Langfuse에 정상 생성됨
- ✅ 턴 메타데이터에 `session_id`, `user_id`, `hostname`, 파트, 메시지 이력 저장 확인
- 진행 문서: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## 주요 기능

- `langfuse_plugin.js` -> `langfuse_hook.py` 이벤트 전달
- Fail-open (오류가 나도 OpenCode 실행 차단 없음)
- `TRACE_TO_LANGFUSE=true` 일 때만 동작
- 지원 환경변수:
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_BASE_URL`
  - `LANGFUSE_USER_ID`
  - `OPENCODE_LANGFUSE_LOG_LEVEL` (`DEBUG|INFO|WARN|ERROR`)
- 턴 재구성 이벤트:
  - `message.updated`
  - `message.part.updated`
- 세션 라이프사이클 trace:
  - `session.created`
  - `session.idle`
  - `session.error`
  - `session.compacted`
- 메타데이터 태그: `opencode`, `product=reconstruction`
- 턴 메타데이터: `session_id`, `user_id`, `hostname`, 턴별 user/assistant part 저장
- 턴 메타데이터에 `message.updated` 이력도 저장 (`message_events.user`, `message_events.assistant`)

## 빠른 설치

```bash
git clone https://github.com/BAEM1N/langfuse-opencode.git
cd langfuse-opencode
bash install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/BAEM1N/langfuse-opencode.git
cd langfuse-opencode
.\install.ps1
```

## 수동 설치

1) SDK 설치

```bash
python3 -m pip install --upgrade langfuse
```

2) 플러그인/훅 복사

```bash
mkdir -p ~/.config/opencode/plugins ~/.config/opencode/hooks ~/.config/opencode/state/langfuse
cp langfuse_plugin.js ~/.config/opencode/plugins/langfuse_plugin.js
cp langfuse_hook.py ~/.config/opencode/hooks/langfuse_hook.py
chmod +x ~/.config/opencode/hooks/langfuse_hook.py
```

3) `~/.config/opencode/.env` 작성

```env
TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_USER_ID=opencode-user
OPENCODE_LANGFUSE_LOG_LEVEL=INFO
OPENCODE_LANGFUSE_MAX_MESSAGE_EVENTS_PER_MESSAGE=30
```

4) `~/.config/opencode/opencode.json` 에 plugin 배열 병합

```json
{
  "plugin": [
    "file:///Users/<you>/.config/opencode/plugins/langfuse_plugin.js"
  ]
}
```

> 기존 설정은 유지하고 plugin 경로만 중복 없이 추가하세요.

## 검증

```bash
python3 -m py_compile langfuse_hook.py
node --check langfuse_plugin.js
```

## 라이선스

MIT
