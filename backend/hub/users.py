"""
요청한 사용자 식별 + 사용자 정보 조회.

1) 식별: 회사 SSO 게이트웨이가 넣어주는 헤더(기본 X-User-Id / X-User-Name / X-User-Dept)를 읽는다.
   헤더가 없으면(로컬 개발) DEV_USER_* 환경변수 사용자로 처리한다.
   ※ 이 헤더는 브라우저가 아니라 게이트웨이가 넣어야 한다 — 게이트웨이 밖에서 백엔드를 직접
     노출하면 누구나 다른 사람 id 를 보낼 수 있다.
2) 정보: USER_INFO_URL 이 있으면 회사 사용자 API 에서 이름/부서/이메일을 받아온다(10분 캐시).
3) 받아온 정보는 users 테이블에 upsert — 메모리 문서와 같은 DB 에 둔다.
"""
import logging
import os
import time
from typing import Optional
from urllib.parse import unquote

import httpx
from fastapi import Request

from db import user_store

log = logging.getLogger("users")

ID_HEADER = os.getenv("USER_ID_HEADER", "X-User-Id")
NAME_HEADER = os.getenv("USER_NAME_HEADER", "X-User-Name")   # 한글은 URL 인코딩해서 넣는다
DEPT_HEADER = os.getenv("USER_DEPT_HEADER", "X-User-Dept")
PROFILE_TTL_S = 600

_profile_cache: dict[str, tuple[float, dict]] = {}


def _header(request: Request, name: str) -> str:
    return unquote(request.headers.get(name, "")).strip()


async def _fetch_profile(user_id: str) -> Optional[dict]:
    """회사 사용자 API — 예) USER_INFO_URL=https://hr.example.com/api/users/{user_id}
    응답 JSON 에서 name / dept / email 키를 읽는다 (키 이름이 다르면 여기만 고친다)."""
    url_tpl = os.getenv("USER_INFO_URL")
    if not url_tpl:
        return None
    hit = _profile_cache.get(user_id)
    if hit and time.time() - hit[0] < PROFILE_TTL_S:
        return hit[1]
    token = os.getenv("USER_INFO_TOKEN")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            res = await client.get(url_tpl.format(user_id=user_id),
                                   headers={"Authorization": f"Bearer {token}"} if token else None)
            res.raise_for_status()
            data = res.json()
    except Exception as e:  # noqa: BLE001 — 사용자 API 장애로 대화가 막히면 안 된다
        log.warning("사용자 정보 조회 실패 (%s): %s", user_id, e)
        return None
    _profile_cache[user_id] = (time.time(), data)
    return data


def admin_ids() -> set[str]:
    """전략 관리자 사번 — .env ADMIN_USERS (쉼표 구분). 모든 스킬을 보고 편집 · 공식 지정 · MCP 서버 관리."""
    return {x.strip() for x in os.getenv("ADMIN_USERS", "2057197").split(",") if x.strip()}


def is_admin(user_id: str) -> bool:
    return user_id in admin_ids()


async def current_user(request: Request) -> dict:
    """FastAPI dependency — {user_id, name, dept, email, profile, ...}"""
    user_id = _header(request, ID_HEADER) or os.getenv("DEV_USER_ID", "dev.user")
    name = _header(request, NAME_HEADER) or os.getenv("DEV_USER_NAME", "개발 사용자")
    dept = _header(request, DEPT_HEADER) or os.getenv("DEV_USER_DEPT", "")
    email = ""

    profile = await _fetch_profile(user_id)
    if profile:
        name = profile.get("name") or name
        dept = profile.get("dept") or dept
        email = profile.get("email") or ""
    return user_store.upsert_user(user_id, name, dept, email, profile) | {"is_admin": is_admin(user_id)}
