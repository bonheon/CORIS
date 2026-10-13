# Coris Skills

skill 하나 = 폴더 하나 = `<id>/SKILL.md`. 업무 workflow 단위로 등록한다.

- tool 은 MCP 서버(mcp_servers.yaml)가 제공한다. 여기서는 이름으로만 참조한다.
- 허브 화면(스킬)에서 만들거나 고쳐도 이 파일이 바뀌고, 에디터로 직접 고쳐도 된다.
- 폴더를 넣으면 skill 이 생기고, 빼면 사라진다 (서버 재시작 불필요).

```
---
name: <폴더명과 같은 id>
title: <화면 표시명>
description: |
  언제 쓰는 skill 인지 — Router 판단 근거
tools:            # 이 workflow 의 필수 tool (MCP tool 이름)
- get_xxx
---

# 절차 본문 — 그대로 프롬프트에 들어간다
1. ...
```

사용 횟수 · 생성 시각은 파일이 아니라 `data/hub.json` 의 `skill_stats` 에 쌓인다.
