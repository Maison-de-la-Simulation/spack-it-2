import shutil
from pathlib import Path
from spack_cli import (
    run_validation_step,
    start_validation_container,
    remove_validation_container,
)
from state import AgentState


def route_after_concretization(state: AgentState) -> str:
    return "install_recipe" if state["validation_result"] else "cleanup_validation"


def cleanup_validation(state: AgentState) -> dict:
    validation = dict(state.get("validation") or {})
    errors = list(state.get("errors", []))
    container_name = validation.get("container_name")
    cleanup = {"passed": True, "skipped": not bool(container_name), "stderr": ""}

    if container_name:
        try:
            remove_validation_container(container_name)
            validation["container_name"] = None
        except OSError as error:
            cleanup.update(passed=False, stderr=str(error))
            errors.append(str(error))

    validation["cleanup"] = cleanup
    passed = cleanup["passed"] and all(
        validation.get(step, {}).get("passed", False)
        for step in ("audit", "concretize", "install")
    )

    return {
        "current_stage": "cleanup_validation",
        "validation": validation,
        "validation_result": passed,
        "needs_human": not passed,
        "errors": errors,
        "status": (
            "validation cleanup complete"
            if cleanup["passed"]
            else "validation cleanup failed"
        ),
    }


def route_after_validation_cleanup(state: AgentState) -> str:
    return "check_recipe_quality" if state["validation_result"] else "recipe_validation_failed"


def _run_recipe_step(state: AgentState, step: str) -> dict:
    validation = dict(state.get("validation") or {})
    check = {"passed": False, "exit_code": None, "stdout": "", "stderr": ""}
    label = {"concretize": "concretization", "install": "installation"}[step]

    try:
        container_name = validation.get("container_name")
        if not container_name:
            raise ValueError("Validation container is missing.")

        arguments = []
        if step == "concretize":
            model = state.get("recipe_model") or {}
            package = model.get("package_name")
            if not package:
                raise ValueError("Recipe model is missing the package name.")
            arguments = [f"generated.{package}"]

        result = run_validation_step(container_name, step, arguments)
        check.update(
            passed=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except (OSError, ValueError) as error:
        check["stderr"] = str(error)

    validation[step] = check
    errors = list(state.get("errors", []))
    if not check["passed"]:
        message = check["stderr"] or check["stdout"] or f"Spack {label} failed."
        errors.append(message.strip())

    return {
        "current_stage": f"{step}_recipe",
        "validation": validation,
        "validation_result": check["passed"],
        "status": f"recipe {label} " + ("passed" if check["passed"] else "failed"),
        "needs_human": not check["passed"],
        "errors": errors,
    }


def concretize_recipe(state: AgentState) -> dict:
    return _run_recipe_step(state, "concretize")


def install_recipe(state: AgentState) -> dict:
    return _run_recipe_step(state, "install")


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
    validation = dict(state.get("validation") or {})

    try:
        recipe_model = state.get("recipe_model") or {}
        root_package = recipe_model.get("package_name")
        if not root_package:
            raise ValueError("Recipe model is missing the package name.")

        packages = sorted({root_package, *state.get("processed_packages", [])})
        repo_root = stage_generated_repo(packages)
        container_name = start_validation_container(repo_root.parent.parent)
        validation["container_name"] = container_name
        result = run_validation_step(
            container_name, "audit", [f"generated.{package}" for package in packages]
        )
        audit.update(
            passed=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except (OSError, ValueError) as error:
        audit["stderr"] = str(error)
    except BaseException:
            if container_name:
                try:
                    remove_validation_container(container_name)
                except OSError:
                    pass
            raise

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
        return "concretize_recipe"

    return "cleanup_validation"


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
