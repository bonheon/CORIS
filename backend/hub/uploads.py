"""
첨부 이미지 저장소 — 채팅 입력창에 붙여넣거나(Ctrl+V) 끌어다 놓은 이미지.

    data/uploads/<id>.<ext>   원본
    data/uploads/<id>.json    {id, name, mime, size, user_id, created_at, description?}

description 은 VLM 해석 결과 캐시 — 같은 이미지가 다음 턴에 다시 와도 VLM 을 또 부르지 않는다.
"""
import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from hub.store import now_iso

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or Path(__file__).resolve().parent.parent / "data" / "uploads")
MAX_BYTES = int(os.getenv("UPLOAD_MAX_MB", "10")) * 1024 * 1024
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_ID = re.compile(r"^up_[0-9a-f]{12}$")


def _meta_path(upload_id: str) -> Path:
    return UPLOAD_DIR / f"{upload_id}.json"


def save(name: str, mime: str, data_b64: str, user_id: str) -> dict:
    if mime not in EXT:
        raise ValueError(f"지원하지 않는 형식: {mime} (png · jpg · webp · gif)")
    raw = base64.b64decode(data_b64.split(",", 1)[-1], validate=False)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"이미지는 {MAX_BYTES // 1024 // 1024}MB 이하만 올릴 수 있습니다")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = "up_" + uuid.uuid4().hex[:12]
    (UPLOAD_DIR / f"{upload_id}.{EXT[mime]}").write_bytes(raw)
    meta = {"id": upload_id, "name": name[:120] or "image", "mime": mime, "size": len(raw),
            "user_id": user_id, "created_at": now_iso()}
    _meta_path(upload_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def get(upload_id: str) -> Optional[dict]:
    if not _ID.match(upload_id or "") or not _meta_path(upload_id).exists():
        return None
    return json.loads(_meta_path(upload_id).read_text(encoding="utf-8"))


def file_path(meta: dict) -> Path:
    return UPLOAD_DIR / f"{meta['id']}.{EXT[meta['mime']]}"


def data_url(meta: dict) -> str:
    return f"data:{meta['mime']};base64,{base64.b64encode(file_path(meta).read_bytes()).decode()}"


def set_description(upload_id: str, description: str) -> None:
    meta = get(upload_id)
    if meta:
        meta["description"] = description
        _meta_path(upload_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def public(meta: dict) -> dict:
    return {k: meta[k] for k in ("id", "name", "mime")}
