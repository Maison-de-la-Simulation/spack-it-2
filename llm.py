import json
import time
import os

import requests


MDLS_URL = "http://localhost:8000/v1/chat/completions"
MDLS_MODEL = "Qwen/Qwen3.8-27B"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def call_mdls(prompt: str) -> str:
    for attempt in range(3):
        try:
            response = requests.post(
                MDLS_URL,
                json={
                    "model": MDLS_MODEL,
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

            response.raise_for_status()
            data = response.json()

        except (requests.RequestException, ValueError) as error:
            if attempt < 2:
                time.sleep(2)
                continue

            raise RuntimeError(f"MDLS request failed: {error}") from error

        if data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content")

            if isinstance(content, str) and content.strip():
                return content.strip()

        if attempt < 2:
            time.sleep(2)

    raise RuntimeError("MDLS returned an empty response")


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
                    "model": OPENROUTER_MODEL,
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

            response.raise_for_status()
            data = response.json()

        except (requests.RequestException, ValueError) as error:
            if attempt < 2:
                time.sleep(2)
                continue

            raise RuntimeError(
                f"OpenRouter request failed: {error}"
            ) from error

        if data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content")

            if isinstance(content, str) and content.strip():
                return content.strip()

        if attempt < 2:
            time.sleep(2)

    raise RuntimeError("OpenRouter returned an empty response")


def call_llm(prompt: str, selected_llm: str) -> str:
    if selected_llm == "mdls":
        return call_mdls(prompt)

    if selected_llm == "open-router":
        return call_openrouter(prompt)

    raise ValueError(f"Unknown LLM: {selected_llm}")


def decide_optional_group(
    package_name: str,
    group_name: str,
    requirements: list[str],
    selected_llm: str = "mdls",
) -> dict:

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

    content = call_llm(prompt, selected_llm)
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
