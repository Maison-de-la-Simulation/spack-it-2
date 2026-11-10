import ast
import logging
import re
from nodes.recipe_generation import _render_dependency
from pathlib import Path

from llm import call_llm

MAX_REPAIR_ATTEMPTS = 2
MAX_REPAIR_LINES = 5
MAX_REPAIR_ISSUES = 3

logger = logging.getLogger(__name__)


def should_repair_recipe(state):
    if state.get("repair_attempts", 0) >= MAX_REPAIR_ATTEMPTS:
        return False

    validation = state.get("validation") or {}
    dependency_check = validation.get("required_dependencies", {})
    missing = dependency_check.get("missing", [])
    if dependency_check.get("passed") is False and not missing:
        return False

    audit = validation.get("audit", {})
    issue_count = len(missing)

    if audit.get("passed") is True:
        cleanup = validation.get("cleanup", {})
        if cleanup.get("passed") is not True or cleanup.get("skipped"):
            return False
    else:
        if not can_repair_audit_failure(validation):
            return False

        logs = audit.get("stderr") or audit.get("stdout") or ""
        counts = re.findall(r"^PKG-[A-Z-]+: (\d+) issues? found", logs, re.MULTILINE)
        audit_issues = sum(int(count) for count in counts)
        if not audit_issues:
            logger.warning("Repair skipped: no issue count in the audit output.")
            return False
        issue_count += audit_issues

    if issue_count > MAX_REPAIR_ISSUES:
        logger.warning(
            "Repair skipped: validation reported %d issues (limit %d).",
            issue_count, MAX_REPAIR_ISSUES,
        )
        return False

    return issue_count > 0


def repair_recipe(state):
    metadata = state["metadata"]
    audit = state["validation"]["audit"]
    provider = state["selected_llm"]

    attempts = state.get("repair_attempts", 0) + 1
    logger.info("Repair attempt %d/%d", attempts, MAX_REPAIR_ATTEMPTS)
    try:
        original_recipe = Path(metadata["generated_recipe_path"]).read_text()
        recipe = state.get("repair_candidate") or original_recipe
        candidate = recipe

        missing = state["validation"].get("required_dependencies", {}).get("missing", [])
        if missing:
            logger.info("Diagnosis: missing required dependencies: %s", ", ".join(missing))

        if not audit["passed"]:
            logger.info(
                "Sending audit log (exit %s) to %s",
                audit.get("exit_code"),
                provider,
            )
            diagnosis = diagnose_failure("audit", audit, provider)
            logger.info("Diagnosis: %s", diagnosis)

            requirements = (
                metadata.get("build_requires", [])
                + metadata.get("dependencies", [])
            )
            if metadata.get("requires_python"):
                requirements.append("python" + metadata["requires_python"])

            candidate = propose_recipe_repair(
                recipe, diagnosis, requirements, provider
            )

        model = state.get("recipe_model") or {}
        new_lines = [
            _render_dependency(dep)
            for dep in model.get("dependencies", [])
            if dep["name"] in missing and not dep.get("when")
        ]
        if new_lines:
            candidate = candidate.rstrip() + "\n" + "\n".join(new_lines) + "\n"
            ast.parse(candidate)

        original_count = len(original_recipe.strip().splitlines())
        previous_additions = recipe.strip().splitlines()[original_count:]
        check_repair_change(original_recipe, candidate, previous_additions + new_lines)
    except (OSError, RuntimeError, ValueError, SyntaxError) as error:
        logger.warning("Repair failed: %s", error)
        return {
            "repair_candidate": None,
            "repair_attempts": attempts,
            "status": "recipe repair failed",
            "errors": state.get("errors", []) + [str(error)],
        }

    logger.info("Rechecking the proposed repair in a fresh validation container.")
    return {
        "repair_candidate": candidate,
        "status": "recipe repair proposed",
        "repair_attempts": attempts,
    }


def route_after_recipe_repair(state):
    if state.get("repair_candidate"):
        return "prepare_validation"

    return "recipe_validation_failed"


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


def diagnose_failure(step, result, selected_llm):
    logs = result.get("stderr") or result.get("stdout") or ""

    prompt = f"""Spack {step} failed with exit code {result.get('exit_code')}.

Explain what failed and what needs to be corrected in 2–3 sentences.
Use the log as evidence. Do not rewrite the recipe or guess a replacement version.

Validation log:
{logs}
"""
    logger.debug("Diagnosis prompt:\n%s", prompt)
    return call_llm(prompt, selected_llm=selected_llm).strip()


def propose_recipe_repair(recipe, diagnosis, upstream_requirements, selected_llm):
    requirements = ", ".join(upstream_requirements) or "Not available"

    prompt = f"""Repair this Spack recipe using the diagnosis below.

Upstream requirements: {requirements}

Keep the package name, source, version, and checksum unchanged.
Fix the reported dependency version problems.
Change only version constraints, on at most {MAX_REPAIR_LINES} lines.
Preserve the upstream dependency constraints.
Return the complete package.py as plain Python, without Markdown fences.

Diagnosis:
{diagnosis}

Recipe:
{recipe}
"""
    logger.debug("Repair prompt:\n%s", prompt)
    candidate = call_llm(prompt, selected_llm=selected_llm).strip()

    if not candidate or candidate == recipe.strip():
        raise ValueError("The LLM did not return a revised recipe.")

    ast.parse(candidate)
    return candidate + "\n"


def check_repair_change(recipe, candidate, added_lines=None):
    added_lines = added_lines or []
    before = recipe.strip().splitlines()
    after = candidate.strip().splitlines()

    if len(after) < len(before) or after[len(before):] != added_lines:
        raise ValueError("Repair added or removed unexpected lines.")

    changes = [(old, new) for old, new in zip(before, after) if old != new]
    line_count = len(changes) + len(added_lines)

    if not line_count:
        raise ValueError("Repair did not change the recipe.")
    if line_count > MAX_REPAIR_LINES:
        raise ValueError(f"Repair changed {line_count} lines; limit is {MAX_REPAIR_LINES}.")

    pattern = r'(\s*depends_on\("[a-z0-9-]+)@[0-9=.,:]+(".*)'
    for old_line, new_line in changes:
        old_match = re.fullmatch(pattern, old_line)
        new_match = re.fullmatch(pattern, new_line)

        if not old_match or not new_match or old_match.groups() != new_match.groups():
            raise ValueError("Repair can only change dependency versions.")

    logger.info("Proposed edits: %d/%d lines changed", line_count, MAX_REPAIR_LINES)
    for old_line, new_line in changes:
        logger.info("- %s\n+ %s", old_line.strip(), new_line.strip())
    for line in added_lines:
        logger.info("+ %s", line.strip())
