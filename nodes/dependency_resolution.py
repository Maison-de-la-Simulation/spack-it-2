from urllib.parse import urlparse
from spack_cli import run_spack_info

import requests

from state import AgentState


def spack_package_exists(package_name: str) -> bool:
    result = run_spack_info(package_name)

    if result.returncode == 0:
        return True

    if "not found in repository" in result.stderr.lower():
        return False

    raise OSError(
        result.stderr.strip() or "Spack dependency check failed"
    )
    return result.returncode == 0

def check_missing_dependencies(state: AgentState) -> dict:
    recipe_model = state.get("recipe_model") or {}
    dependencies = recipe_model.get("dependencies", [])
    processed_packages = state.get("processed_packages", [])

    missing = []

    for dependency in dependencies:
        name = dependency.get("name")

        if not name or name == "python":
            continue

        if name in processed_packages:
            continue

        if not spack_package_exists(name):
            missing.append(name)

    missing = sorted(set(missing))

    return {
        "missing_dependencies": missing,
        "current_dependency": missing[0] if missing else None,
        "dependency_repo_url": None,
        "current_stage": "check_missing_dependencies",
        "status": "dependencies checked",
    }


def route_after_dependency_check(state: AgentState) -> str:
    if state.get("current_dependency"):
        return "resolve_dependency_source"

    return "check_recipe_inputs"


def resolve_dependency_source(state: AgentState) -> dict:
    dependency_name = state.get("current_dependency")

    if not dependency_name:
        return {
            "dependency_repo_url": None,
            "current_stage": "resolve_dependency_source",
            "status": "dependency source unresolved",
        }

    pypi_name = dependency_name.removeprefix("py-")

    try:
        response = requests.get(
            f"https://pypi.org/pypi/{pypi_name}/json",
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return {
            "dependency_repo_url": None,
            "current_stage": "resolve_dependency_source",
            "status": "dependency source unresolved",
        }

    info = data.get("info", {})
    project_urls = info.get("project_urls") or {}
    candidates = list(project_urls.values())

    if info.get("home_page"):
        candidates.append(info["home_page"])

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue

        parsed = urlparse(candidate)

        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            continue

        parts = [part for part in parsed.path.split("/") if part]

        if len(parts) < 2:
            continue

        repo_url = (
            f"https://github.com/"
            f"{parts[0]}/{parts[1].removesuffix('.git')}"
        )

        return {
            "dependency_repo_url": repo_url,
            "current_stage": "resolve_dependency_source",
            "status": "dependency source resolved",
        }

    return {
        "dependency_repo_url": None,
        "current_stage": "resolve_dependency_source",
        "status": "dependency source unresolved",
    }


def route_after_dependency_source(state: AgentState) -> str:
    if state.get("dependency_repo_url"):
        return "check_recursion_guard"

    return "dependency_source_unresolved"


def check_recursion_guard(state: AgentState) -> dict:
    dependency_name = state.get("current_dependency")
    remaining_depth = state.get("remaining_depth", 0)
    dependency_path = state.get("dependency_path", [])

    if remaining_depth <= 0:
        status = "recursion depth reached"
    elif dependency_name in dependency_path:
        status = "dependency cycle detected"
    else:
        status = "recursion allowed"

    return {
        "current_stage": "check_recursion_guard",
        "status": status,
    }


def route_after_recursion_guard(state: AgentState) -> str:
    if state.get("status") == "recursion depth reached":
        return "recursion_depth_reached"

    if state.get("status") == "dependency cycle detected":
        return "dependency_cycle_detected"

    return "package_dependency_recursively"


def package_dependency_recursively(state: AgentState) -> dict:
    dependency_name = state.get("current_dependency")
    dependency_repo_url = state.get("dependency_repo_url")

    if not dependency_name or not dependency_repo_url:
        return {
            "current_stage": "package_dependency_recursively",
            "status": "dependency recursion failed",
            "needs_human": True,
        }

    # Import here to avoid a circular import when graph.py loads this module.
    from graph import graph

    dependency_path = list(state.get("dependency_path", []))
    processed_packages = list(state.get("processed_packages", []))
    remaining_depth = state.get("remaining_depth", 0)

    recipe_model = state.get("recipe_model") or {}
    current_package = recipe_model.get("package_name")

    if current_package:
        dependency_path.append(current_package)

    child_state = graph.invoke(
        {
            "repo_url": dependency_repo_url,
            "remaining_depth": remaining_depth - 1,
            "dependency_path": dependency_path,
            "processed_packages": processed_packages,
            "selected_llm": state.get("selected_llm", "mdls"),
        }
    )

    if child_state.get("status") != "recipe generated":
        return {
            "current_stage": "package_dependency_recursively",
            "status": "recursive dependency failed",
            "errors": state.get("errors", [])
            + child_state.get("errors", [])
            + [f"failed to package dependency {dependency_name}"],
            "needs_human": True,
        }

    for package in child_state.get("processed_packages", []):
        if package not in processed_packages:
            processed_packages.append(package)

    child_recipe_model = child_state.get("recipe_model") or {}
    child_package = child_recipe_model.get("package_name")

    if child_package and child_package not in processed_packages:
        processed_packages.append(child_package)

    return {
        "processed_packages": processed_packages,
        "current_dependency": None,
        "dependency_repo_url": None,
        "current_stage": "package_dependency_recursively",
        "status": "recursive dependency packaged",
    }


def route_after_recursive_dependency(state: AgentState) -> str:
    if state.get("status") == "recursive dependency packaged":
        return "check_missing_dependencies"

    return "recursive_dependency_failed"


def dependency_source_unresolved(state: AgentState) -> dict:
    """Stop when the dependency repository cannot be resolved."""
    return {
        "current_stage": "dependency_source_unresolved",
        "status": "dependency source unresolved",
        "needs_human": True,
    }


def recursive_dependency_failed(state: AgentState) -> dict:
    """Stop when recursive dependency packaging fails."""
    return {
        "current_stage": "recursive_dependency_failed",
        "status": "recursive dependency packaging failed",
        "needs_human": True,
    }


def recursion_depth_reached(state: AgentState) -> dict:
    """Stop when the maximum recursion depth is reached."""
    return {
        "current_stage": "recursion_depth_reached",
        "status": "maximum recursion depth reached",
        "needs_human": True,
    }


def dependency_cycle_detected(state: AgentState) -> dict:
    """Stop when a dependency cycle is detected."""
    return {
        "current_stage": "dependency_cycle_detected",
        "status": "dependency cycle detected",
        "needs_human": True,
    }
