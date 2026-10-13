"""
Skill 저장소 — skill 하나 = 폴더 하나 = skills/<id>/SKILL.md (ceeria 와 같은 형식).

    ---
    name: sk_morning                 # = 폴더명(id)
    title: 출근 전 라인 점검          # 화면 표시명 (없으면 name)
    description: |
      언제 쓰는 skill 인지 — Router 판단 근거
    tools: [get_daily_report, ...]   # MCP tool 이름 — 이 skill 의 필수 tool
    ---

    # 절차 본문 — 그대로 프롬프트에 들어간다

파일이 원본이라 화면에서 고쳐도, 에디터로 고쳐도, 폴더를 넣고 빼도 같은 결과가 된다.
사용 횟수 · 생성 시각처럼 실행하면서 바뀌는 값은 파일이 아니라 store 의 skill_stats 에 둔다
(파일을 매 실행마다 고쳐 쓰지 않도록).

API 로 나가는 모양은 예전 hub.json skill 과 같다:
    {id, name, description, tools, instructions, uses, created_at, updated_at, path}
"""
import logging
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from hub import store

log = logging.getLogger("skills")

SKILLS_DIR = Path(os.getenv("SKILLS_DIR") or Path(__file__).resolve().parent.parent / "skills")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # 폴더명으로 쓰므로 경로 문자를 막는다
_lock = threading.Lock()


# ── SKILL.md 읽기 · 쓰기 ─────────────────────────────────────────

def _split(text: str, path: Path) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError(f"{path}: '---' 로 시작하는 frontmatter 가 필요합니다")
    head, sep, body = text[3:].partition("\n---")
    if not sep:
        raise ValueError(f"{path}: frontmatter 를 닫는 '---' 이 없습니다")
    return yaml.safe_load(head) or {}, body.lstrip("-").lstrip("\n")


def _render(skill_id: str, name: str, description: str, tools: list[str], instructions: str) -> str:
    meta = {"name": skill_id, "title": name, "description": description.strip(), "tools": list(tools)}
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{head}---\n\n{instructions.strip()}\n"


def _stats(skill_id: str) -> dict:
    return store.get_item("skill_stats", skill_id) or {"id": skill_id, "uses": 0, "created_at": None}


def _load(path: Path) -> Optional[dict]:
    skill_id = path.parent.name
    try:
        meta, body = _split(path.read_text(encoding="utf-8"), path)
    except Exception:  # noqa: BLE001 — 깨진 파일 하나 때문에 목록 전체가 죽으면 안 된다
        log.exception("SKILL.md 읽기 실패: %s", path)
        return None
    st = _stats(skill_id)
    updated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return {
        "id": skill_id,
        "name": str(meta.get("title") or meta.get("name") or skill_id),
        "description": str(meta.get("description") or "").strip(),
        "tools": [str(t) for t in meta.get("tools") or []],
        "instructions": body.strip(),
        "uses": st.get("uses", 0),
        "created_at": st.get("created_at") or updated,
        "updated_at": updated,
        "path": str(path.relative_to(SKILLS_DIR.parent)) if path.is_relative_to(SKILLS_DIR.parent) else str(path),
    }


def _path(skill_id: str) -> Path:
    return SKILLS_DIR / skill_id / "SKILL.md"


# ── 조회 · 저장 (store 와 같은 이름) ─────────────────────────────

def list_items() -> list[dict]:
    if not SKILLS_DIR.exists():
        return []
    skills = [s for p in sorted(SKILLS_DIR.glob("*/SKILL.md")) if (s := _load(p))]
    return sorted(skills, key=lambda s: s["updated_at"], reverse=True)


def get_item(skill_id: Optional[str]) -> Optional[dict]:
    if not skill_id or not _ID_RE.match(skill_id):
        return None
    path = _path(skill_id)
    return _load(path) if path.exists() else None


def save(skill_id: Optional[str], name: str, description: str, tools: list[str], instructions: str) -> dict:
    """skill_id 가 없으면 새로 만든다."""
    with _lock:
        new = skill_id is None
        skill_id = skill_id or store.new_id("sk")
        if not _ID_RE.match(skill_id):
            raise ValueError(f"잘못된 skill id: {skill_id}")
        path = _path(skill_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(skill_id, name, description, tools, instructions), encoding="utf-8")
        if new:
            store.upsert_item("skill_stats", {"id": skill_id, "uses": 0, "created_at": store.now_iso()})
    return get_item(skill_id)


def delete_item(skill_id: str) -> bool:
    if not _ID_RE.match(skill_id) or not _path(skill_id).exists():
        return False
    with _lock:
        shutil.rmtree(SKILLS_DIR / skill_id)
        store.delete_item("skill_stats", skill_id)
    return True


def count_use(skill_id: str) -> None:
    st = _stats(skill_id)
    st["uses"] = st.get("uses", 0) + 1
    store.upsert_item("skill_stats", st)


# ── 이전 저장 방식(hub.json skills)에서 옮기기 ───────────────────

def migrate_from_store() -> int:
    """hub.json 에 남은 skill 을 SKILL.md 로 옮긴다. 기동 시 1회 — 옮긴 뒤 hub.json 에서 지운다.

    같은 id 의 폴더가 이미 있으면 파일 쪽을 원본으로 보고 사용 횟수만 가져온다.
    """
    moved = 0
    for old in store.list_items("skills"):
        sid = old["id"]
        if _ID_RE.match(sid) and not _path(sid).exists():
            save(sid, old.get("name", sid), old.get("description", ""), old.get("tools", []), old.get("instructions", ""))
            moved += 1
        store.upsert_item("skill_stats", {"id": sid, "uses": old.get("uses", 0), "created_at": old.get("created_at")})
        store.delete_item("skills", sid)
    if moved:
        log.info("hub.json skill %d개를 %s 로 옮김", moved, SKILLS_DIR)
    return moved
