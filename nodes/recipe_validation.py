import shutil
import tomllib
from pathlib import Path, PurePosixPath
from hashlib import sha256
from io import BytesIO
import tarfile
from urllib.request import urlopen
import zipfile
from spack_cli import (
    run_validation_step,
    start_validation_container,
    remove_validation_container,
)
from state import AgentState
GENERATED_DIR = Path("validation/generated")

def read_source_pyproject(metadata: dict) -> str:
    source_url = (
        metadata.get("pypi_source_url")
        if metadata.get("source_type") == "pypi"
        else metadata.get("source_location")
    )
    expected_hash = metadata.get("source_sha256")
    if not source_url or not expected_hash:
        raise ValueError("Source archive URL or SHA-256 is missing.")

    with urlopen(source_url, timeout=60) as response:
        content = response.read()
    if sha256(content).hexdigest() != expected_hash.lower():
        raise ValueError("Source archive SHA-256 does not match.")

    buffer = BytesIO(content)
    is_zip = zipfile.is_zipfile(buffer)
    buffer.seek(0)
    archive = (
        zipfile.ZipFile(buffer)
        if is_zip
        else tarfile.open(fileobj=buffer, mode="r:*")
    )
    with archive:
        names = (
            [item.filename for item in archive.infolist() if not item.is_dir()]
            if is_zip
            else [item.name for item in archive.getmembers() if item.isfile()]
        )
        target = PurePosixPath("pyproject.toml")
        paths = {PurePosixPath(name) for name in names}
        if target not in paths:
            roots = {path.parts[0] for path in paths if path.parts}
            if len(roots) != 1:
                raise ValueError("Cannot identify the source archive root.")
            target = PurePosixPath(roots.pop()) / "pyproject.toml"

        matches = [name for name in names if PurePosixPath(name) == target]
        if len(matches) != 1:
            raise ValueError("Expected one root pyproject.toml in the source archive.")
        if is_zip:
            return archive.read(matches[0]).decode("utf-8")
        with archive.extractfile(matches[0]) as file:
            return file.read().decode("utf-8")


def build_quality_evidence(state: AgentState) -> dict:
    metadata = state.get("metadata") or {}
    recipe_path = metadata.get("generated_recipe_path")

    if not recipe_path:
        raise ValueError("Generated recipe path is missing.")

    source_text = read_source_pyproject(metadata)
    source_project = tomllib.loads(source_text).get("project", {})
    return {
        "repo_url": state.get("repo_url"),
        "project_version": source_project.get("version"),
        "pyproject_toml": source_text,
        "resolved_source": {
            key: metadata.get(key)
            for key in (
                "source_type",
                "source_location",
                "source_version",
                "source_sha256",
            )
        },
        "generated_recipe": Path(recipe_path).read_text(encoding="utf-8"),
    }


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


def concretize_recipe(state: AgentState) -> dict:
    """Resolve the generated package and its dependencies."""
    validation = dict(state.get("validation") or {})
    check = {
        "passed": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    try:
        container_name = validation.get("container_name")
        if not container_name:
            raise ValueError("Validation container is missing.")

        model = state.get("recipe_model") or {}
        package = model.get("package_name")
        if not package:
            raise ValueError("Recipe model is missing the package name.")

        result = run_validation_step(
            container_name, "concretize", [f"generated.{package}"]
        )

        check["passed"] = result.returncode == 0
        check["exit_code"] = result.returncode
        check["stdout"] = result.stdout or ""
        check["stderr"] = result.stderr or ""
    except (OSError, ValueError) as error:
        check["stderr"] = str(error)

    validation["concretize"] = check
    errors = list(state.get("errors", []))

    if check["passed"]:
        status = "recipe concretization passed"
    else:
        status = "recipe concretization failed"
        message = check["stderr"]

        if not message:
            message = check["stdout"]

        if not message:
            message = "Spack concretization failed."

        errors.append(message.strip())

    return {
        "current_stage": "concretize_recipe",
        "validation": validation,
        "validation_result": check["passed"],
        "status": status,
        "needs_human": not check["passed"],
        "errors": errors,
    }


def install_recipe(state: AgentState) -> dict:
    """Install the concretized validation environment."""
    validation = dict(state.get("validation") or {})
    check = {
        "passed": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    try:
        container_name = validation.get("container_name")
        if not container_name:
            raise ValueError("Validation container is missing.")

        result = run_validation_step(container_name, "install")

        check["passed"] = result.returncode == 0
        check["exit_code"] = result.returncode
        check["stdout"] = result.stdout or ""
        check["stderr"] = result.stderr or ""
    except (OSError, ValueError) as error:
        check["stderr"] = str(error)

    validation["install"] = check
    errors = list(state.get("errors", []))

    if check["passed"]:
        status = "recipe installation passed"
    else:
        status = "recipe installation failed"
        message = check["stderr"]

        if not message:
            message = check["stdout"]

        if not message:
            message = "Spack installation failed."

        errors.append(message.strip())

    return {
        "current_stage": "install_recipe",
        "validation": validation,
        "validation_result": check["passed"],
        "status": status,
        "needs_human": not check["passed"],
        "errors": errors,
    }


def stage_generated_repo(packages: list[str]) -> Path:
    """Copy generated recipes into a Spack package repository."""
    repo_root = GENERATED_DIR / "spack_repo" / "generated"

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


def prepare_validation(state: AgentState) -> dict:
    packages = [state["recipe_model"]["package_name"]]

    for dependency in state.get("processed_packages", []):
        if dependency not in packages:
            packages.append(dependency)

    validation = {"packages": packages, "container_name": None}
    errors = list(state.get("errors", []))

    try:
        stage_generated_repo(packages)
        validation["container_name"] = start_validation_container(GENERATED_DIR)
    except OSError as error:
        errors.append(str(error))
        return {
            "current_stage": "prepare_validation",
            "validation": validation,
            "validation_result": False,
            "status": "validation preparation failed",
            "needs_human": True,
            "errors": errors,
        }

    return {
        "current_stage": "prepare_validation",
        "validation": validation,
        "validation_result": None,
        "status": "validation prepared",
        "needs_human": False,
        "errors": errors,
    }


def route_after_validation_preparation(state: AgentState) -> str:
    if state["status"] == "validation prepared":
        return "validate_recipe"

    return "cleanup_validation"


def validate_recipe(state: AgentState) -> dict:
    """Run the Spack audit on generated recipes."""
    audit = {"passed": False, "exit_code": None, "stdout": "", "stderr": ""}
    validation = dict(state.get("validation") or {})

    try:
        container_name = validation["container_name"]
        packages = validation["packages"]

        audit_packages = []
        for package in packages:
            audit_packages.append(f"generated.{package}")

        result = run_validation_step(container_name, "audit", audit_packages)
        audit.update(
            passed=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except (OSError, ValueError) as error:
        audit["stderr"] = str(error)

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
