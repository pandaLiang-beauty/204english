from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIProviderError(RuntimeError):
    def __init__(self, user_message: str, diagnostic: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.diagnostic = diagnostic or user_message


def http_status_for_ai_error(exc: AIProviderError) -> int:
    diagnostic = (exc.diagnostic or "").lower()
    user_message = (exc.user_message or "").lower()
    if "http 429" in diagnostic or "quota" in diagnostic or "rate limit" in diagnostic:
        return 429
    if "未配置" in user_message:
        return 400
    return 424


def _chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    disable_thinking: bool | None = None,
    timeout_seconds: float | None = None,
) -> str:
    base_url = str(base_url or "").strip().rstrip("/")
    api_key = str(api_key or "").strip()
    selected_model = str(model or "").strip()
    if not base_url or not api_key:
        raise AIProviderError("AI 服务未配置")

    selected_temperature = temperature
    if selected_temperature is None:
        selected_temperature = 0.2
    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "temperature": selected_temperature,
    }
    selected_reasoning_effort = reasoning_effort
    if selected_reasoning_effort:
        payload["reasoning_effort"] = selected_reasoning_effort
    selected_disable_thinking = disable_thinking
    if selected_disable_thinking:
        payload["thinking"] = {"type": "disabled"}

    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "english-review/1.0",
        },
        method="POST",
    )
    try:
        selected_timeout = timeout_seconds
        if selected_timeout is None:
            selected_timeout = 120
        with urlopen(request, timeout=selected_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIProviderError(
            "AI 服务暂时无法完成分析，请稍后重试。",
            f"AI provider HTTP {exc.code}: {detail[:1000]}",
        ) from exc
    except TimeoutError as exc:
        raise AIProviderError("AI 服务响应超时，请稍后重试。", f"AI provider request timed out: {exc}") from exc
    except URLError as exc:
        raise AIProviderError("AI 服务网络请求失败，请稍后重试。", f"AI provider request failed: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AIProviderError(
            "AI 服务返回了无效响应，请稍后重试。",
            f"AI provider response was not valid JSON: {exc}",
        ) from exc
    except ValueError as exc:
        raise AIProviderError(
            "AI 服务配置或响应无效，请稍后重试。",
            f"AI provider request/response value error: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise AIProviderError(
            "AI 服务未返回有效分析结果",
            f"AI provider response was {type(data).__name__}, expected object",
        )
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AIProviderError("AI 服务未返回有效分析结果", f"AI provider returned no choices: {str(data)[:1000]}")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    if isinstance(content, list):
        text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    else:
        text = str(content or "").strip()
    if text:
        return text
    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, list):
        text = "\n".join(
            str(item.get("text", "")) for item in reasoning_content if isinstance(item, dict)
        ).strip()
    else:
        text = str(reasoning_content or "").strip()
    if text:
        return text
    raise AIProviderError(
        "AI 服务未返回有效分析结果",
        f"AI provider returned an empty message; keys={sorted(message.keys())}",
    )
