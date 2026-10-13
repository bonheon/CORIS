"""
LLM 생성 — agent · Router · 메모리가 모두 여기서 모델을 받는다.

회사 LLM 게이트웨이(OpenAI 호환)로 옮길 때는 .env 의 LLM_BASE_URL · LLM_API_KEY · *_MODEL 만 바꾼다.
LLM_BASE_URL 이 비어 있으면 OpenAI 기본 주소를 쓴다.
"""
import os
from typing import Optional

from langchain_openai import ChatOpenAI


def chat_model(model: str, *, temperature: Optional[float] = None, streaming: bool = False) -> ChatOpenAI:
    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(
        model=model,
        api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL") or None,
        streaming=streaming,
        **kwargs,
    )


def vision_model() -> ChatOpenAI:
    """이미지 해석 모델(VLM) — 사내 vLLM 등 OpenAI 호환 서버. VISION_* 가 비어 있으면 LLM_* 를 쓴다.

    vLLM 예) VISION_BASE_URL=http://vlm.company:8000/v1  VISION_MODEL=Qwen2.5-VL-7B-Instruct  VISION_API_KEY=EMPTY
    """
    return ChatOpenAI(
        model=os.getenv("VISION_MODEL", "gpt-4o"),
        api_key=os.getenv("VISION_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("VISION_BASE_URL") or os.getenv("LLM_BASE_URL") or None,
        temperature=0,
        max_tokens=int(os.getenv("VISION_MAX_TOKENS", "1500")),
    )
