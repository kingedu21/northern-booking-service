from __future__ import annotations

from typing import Any, Dict, Tuple

from django.conf import settings


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text.strip()

    output = getattr(response, "output", None) or []
    parts = []
    for item in output:
        for content in (getattr(item, "content", None) or []):
            if getattr(content, "type", "") == "output_text":
                val = getattr(content, "text", "")
                if val:
                    parts.append(val)
    return "\n".join(parts).strip()


def generate_admin_insights(metrics: Dict[str, Any]) -> Tuple[str, str]:
    api_key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    model = (getattr(settings, "OPENAI_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini").strip()
    timeout = int(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 20))

    if not api_key:
        return "", "OPENAI_API_KEY is not configured."

    try:
        from openai import OpenAI
    except Exception:
        return "", "OpenAI SDK is not installed. Run: pip install openai"

    prompt = (
        "You are a railway revenue analyst. "
        "Analyze the metrics and provide: "
        "1) short executive summary, "
        "2) top 3 opportunities, "
        "3) top 3 risks, "
        "4) 3 concrete actions for next 7 days. "
        "Use concise bullet points."
    )

    client = OpenAI(api_key=api_key, timeout=timeout)
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(metrics)},
            ],
            max_output_tokens=700,
        )
        text = _extract_response_text(response)
        if not text:
            return "", "OpenAI returned an empty response."
        return text, ""
    except Exception as exc:
        return "", f"OpenAI request failed: {exc}"
