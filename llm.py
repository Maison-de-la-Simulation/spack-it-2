import json
import os
import time

import requests


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def call_openrouter(prompt: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    for attempt in range(3):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    "temperature": 0.1,
                },
                timeout=60,
            )

            data = response.json()

        except (requests.RequestException, ValueError) as error:
            if attempt < 2:
                time.sleep(2)
                continue

            raise RuntimeError(f"OpenRouter request failed: {error}") from error

        if data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content")

            if isinstance(content, str) and content.strip():
                return content

            if attempt < 2:
                time.sleep(2)
                continue

            raise RuntimeError("OpenRouter returned an empty response")

        message = data.get("error", {}).get("message", "OpenRouter request failed")

        if "temporarily overloaded" not in message.lower():
            raise RuntimeError(message)

        if attempt < 2:
            time.sleep(2)

    raise RuntimeError(message)


NON_VARIANT_GROUPS = {
    "test",
    "tests",
    "dev",
    "development",
    "docs",
    "documentation",
    "lint",
    "typing",
}


def decide_optional_group(
    package_name: str,
    group_name: str,
    requirements: list[str],
) -> dict:
    if group_name.lower() in NON_VARIANT_GROUPS:
        return {
            "create_variant": False,
            "confidence": "high",
            "reason": f"'{group_name}' is a development or testing dependency group",
            "decision_source": "rule",
        }

    evidence = {
        "package": package_name,
        "optional_group": group_name,
        "requirements": requirements,
    }

    prompt = f"""
You are helping decide how upstream Python optional dependencies should be
represented in a Spack recipe.

Upstream evidence:
{json.dumps(evidence, indent=2)}

Decide whether this optional dependency group should become a Spack variant.

Return JSON only with exactly these fields:

{{
  "create_variant": true,
  "confidence": "high",
  "reason": "short explanation"
}}

Rules:
- Base the decision only on the evidence provided.
- Do not invent dependencies or package metadata.
- confidence must be one of: high, medium, low.
"""

    content = call_openrouter(prompt)
    result = json.loads(content)

    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object")

    required_fields = {
        "create_variant",
        "confidence",
        "reason",
    }

    if set(result) != required_fields:
        raise ValueError("unexpected LLM response fields")

    if not isinstance(result["create_variant"], bool):
        raise ValueError("create_variant must be a boolean")

    if not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("reason must be a non-empty string")

    if (
        not isinstance(result["confidence"], str)
        or result["confidence"] not in {"high", "medium", "low"}
    ):
        raise ValueError("invalid confidence value")

    result["decision_source"] = "llm"
    return result