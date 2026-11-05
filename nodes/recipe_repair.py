import ast
import re
from pathlib import Path

from llm import call_llm

MAX_REPAIR_ATTEMPTS = 2


def diagnose_failure(step, result, selected_llm):
    logs = result.get("stderr") or result.get("stdout") or ""

    prompt = f"""Spack {step} failed with exit code {result.get('exit_code')}.

Explain what failed and what needs to be corrected in 2–3 sentences.
Use the log as evidence. Do not rewrite the recipe or guess a replacement version.

Validation log:
{logs}
"""

    return call_llm(prompt, selected_llm=selected_llm).strip()


def check_repair_change(recipe, candidate):
    before = recipe.strip().splitlines()
    after = candidate.strip().splitlines()

    if len(before) != len(after):
        raise ValueError("Repair must change only one dependency version.")

    changes = [(old, new) for old, new in zip(before, after) if old != new]

    if len(changes) != 1:
        raise ValueError("Repair must change only one dependency version.")

    old_line, new_line = changes[0]
    pattern = r'(\s*depends_on\("[a-z0-9-]+)@[0-9=.,:]+(".*)'
    old_match = re.fullmatch(pattern, old_line)
    new_match = re.fullmatch(pattern, new_line)

    if not old_match or not new_match or old_match.groups() != new_match.groups():
        raise ValueError("Repair changed more than the dependency version.")


def propose_recipe_repair(recipe, diagnosis, build_requirements, selected_llm):
    requirements = ", ".join(build_requirements) or "Not available"

    prompt = f"""Repair this Spack recipe using the diagnosis below.

Upstream build requirements: {requirements}

Keep the package name, source, version, and checksum unchanged.
Make the smallest change needed to fix the failure.
Preserve the upstream dependency constraints.
Return the complete package.py as plain Python, without Markdown fences.

Diagnosis:
{diagnosis}

Recipe:
{recipe}
"""

    candidate = call_llm(prompt, selected_llm=selected_llm).strip()

    if not candidate or candidate == recipe.strip():
        raise ValueError("The LLM did not return a revised recipe.")

    ast.parse(candidate)
    check_repair_change(recipe, candidate)
    return candidate + "\n"


def can_repair_audit_failure(validation):
    cleanup = validation.get("cleanup", {})
    audit = validation.get("audit", {})
    exit_code = audit.get("exit_code")

    return (
        cleanup.get("passed") is True
        and not cleanup.get("skipped")
        and audit.get("passed") is False
        and exit_code is not None
        and exit_code > 0
    )


def should_repair_recipe(state):
    return (
        state.get("repair_attempts", 0) < MAX_REPAIR_ATTEMPTS
        and can_repair_audit_failure(state.get("validation") or {})
    )


def repair_recipe(state):
    metadata = state["metadata"]
    audit = state["validation"]["audit"]
    provider = state["selected_llm"]

    attempts = state.get("repair_attempts", 0) + 1
    try:
        recipe = state.get("repair_candidate")
        if not recipe:
            recipe = Path(metadata["generated_recipe_path"]).read_text()
            diagnosis = diagnose_failure("audit", audit, provider)
            candidate = propose_recipe_repair(
                recipe,
                diagnosis,
                metadata.get("build_requires", []),
                provider,
            )
    except (OSError, RuntimeError, ValueError, SyntaxError) as error:
        return {
            "repair_candidate": None,
            "repair_attempts": attempts,
            "status": "recipe repair failed",
            "errors": state.get("errors", []) + [str(error)],
        }

    return {
        "repair_candidate": candidate,
        "status": "recipe repair proposed",
        "repair_attempts": attempts,
    }


def route_after_recipe_repair(state):
    if state.get("repair_candidate"):
        return "prepare_validation"

    return "recipe_validation_failed"
