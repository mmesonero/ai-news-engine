from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI, RateLimitError
from openai._exceptions import APIError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


_RETRYABLE = (RateLimitError, APIError, APIStatusError)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
async def embed_batch(texts: list[str]) -> list[list[float]]:
    client = get_client()
    res = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    log.info(
        "openai.embed",
        model=settings.openai_embedding_model,
        n=len(texts),
        tokens=res.usage.total_tokens if res.usage else None,
    )
    return [d.embedding for d in res.data]


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)
async def json_completion(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    client = get_client()
    res = await client.chat.completions.create(
        model=model or settings.openai_llm_model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    if res.usage:
        log.info(
            "openai.completion",
            model=model or settings.openai_llm_model,
            prompt_tokens=res.usage.prompt_tokens,
            completion_tokens=res.usage.completion_tokens,
        )
    content = res.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        log.warning("openai.json_decode_failed", raw=content[:200])
        return {}
