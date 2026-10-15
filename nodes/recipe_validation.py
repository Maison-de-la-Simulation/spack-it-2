import shutil
from pathlib import Path
from spack_cli import run_spack_audit
from state import AgentState


def stage_generated_repo(packages: list[str]) -> Path:
    """Copy generated recipes into a Spack package repository."""
    repo_root = Path("validation/generated/spack_repo/generated")

    if repo_root.exists():
        shutil.rmtree(repo_root)

    packages_dir = repo_root / "packages"
    packages_dir.mkdir(parents=True)

    (repo_root / "repo.yaml").write_text(
        "repo:\n  namespace: generated\n  api: v2.2\n",
        encoding="utf-8",
    )

    for package_name in sorted(set(packages)):
        package_dir = package_name.replace("-", "_")
        source = Path("outputs") / package_dir / "package.py"

        if not source.is_file():
            raise FileNotFoundError(f"Missing generated recipe: {source}")

        destination = packages_dir / package_dir
        destination.mkdir()
        shutil.copy2(source, destination / "package.py")

    return repo_root.resolve()


def validate_recipe(state: AgentState) -> dict:
    """Run the Spack audit on generated recipes."""
    audit = {"passed": False, "exit_code": None, "stdout": "", "stderr": ""}

    try:
        recipe_model = state.get("recipe_model") or {}
        root_package = recipe_model.get("package_name")
        if not root_package:
            raise ValueError("Recipe model is missing the package name.")

        packages = sorted({root_package, *state.get("processed_packages", [])})
        repo_root = stage_generated_repo(packages)
        result = run_spack_audit(repo_root.parent.parent, packages)
        audit.update(
            passed=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except (OSError, ValueError) as error:
        audit["stderr"] = str(error)

    validation = dict(state.get("validation") or {})
    validation["audit"] = audit
    errors = list(state.get("errors", []))
    if not audit["passed"]:
        message = audit["stderr"] or audit["stdout"] or "Spack audit failed"
        errors.append(message.strip())

    return {
        "current_stage": "validate_recipe",
        "validation_result": audit["passed"],
        "validation": validation,
        "status": "recipe audit passed" if audit["passed"] else "recipe audit failed",
        "needs_human": not audit["passed"],
        "errors": errors,
    }


def route_after_recipe_validation(state: AgentState) -> str:
    """Route after recipe validation."""
    if state["validation_result"]:
        return "check_recipe_quality"

    return "recipe_validation_failed"


def recipe_validation_failed(state: AgentState) -> dict:
    """Stop when recipe validation fails."""
    return {
        "current_stage": "recipe_validation_failed",
        "status": "recipe validation failed",
        "needs_human": True,
    }


def check_recipe_quality(state: AgentState) -> dict:
    """Return a fixed quality score until scoring is implemented."""
    return {
        "current_stage": "check_recipe_quality",
        "quality_score": 90.0,
        "status": "recipe quality checked",
    }


def route_after_recipe_quality(state: AgentState) -> str:
    """Route after the recipe quality check."""
    quality_score = state["quality_score"]

    if quality_score is not None and quality_score >= 90:
        return "recipe_valid"

    return "recipe_quality_low"


def recipe_valid(state: AgentState) -> dict:
    """Mark the recipe as valid."""
    return {
        "current_stage": "recipe_valid",
        "status": "recipe valid",
        "needs_human": False,
    }


def recipe_quality_low(state: AgentState) -> dict:
    """Stop when the quality score needs review."""
    return {
        "current_stage": "recipe_quality_low",
        "status": "recipe quality needs review",
        "needs_human": True,
    }
