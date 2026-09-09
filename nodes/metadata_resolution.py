import hashlib
import subprocess
import re
import tomllib
import requests
from pathlib import Path

from state import AgentState


def extract_metadata(state: AgentState) -> dict:
    """Extract project metadata from pyproject.toml."""
    repo_path = Path(state["repo_path"])
    metadata = dict(state["metadata"])
    pyproject_path = repo_path / "pyproject.toml"

    if not pyproject_path.exists():
        return {
            "current_stage": "extract_metadata",
            "status": "failed",
            "errors": state["errors"] + ["pyproject.toml not found"],
        }

    try:
        with pyproject_path.open("rb") as file:
            pyproject = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        return {
            "current_stage": "extract_metadata",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }

    project = pyproject.get("project", {})
    build_system = pyproject.get("build-system", {})
    urls = project.get("urls", {})

    project_version = project.get("version")
    dynamic_version = _read_dynamic_version(repo_path, pyproject)

    metadata["project_name"] = project.get("name")
    metadata["description"] = project.get("description")
    metadata["project_version"] = project_version or dynamic_version
    metadata["version_source"] = (
        "project.version" if project_version else "dynamic"
    )
    metadata["dynamic_fields"] = project.get("dynamic", [])
    metadata["requires_python"] = project.get("requires-python")
    metadata["license"] = _normalize_license(project.get("license"))
    metadata["homepage"] = urls.get("Homepage") or urls.get("homepage")
    metadata["source_url"] = urls.get("Source") or urls.get("source")
    metadata["dependencies"] = project.get("dependencies", [])
    metadata["optional_dependencies"] = project.get(
        "optional-dependencies", {}
    )
    metadata["build_backend"] = build_system.get("build-backend")
    metadata["build_requires"] = build_system.get("requires", [])

    package_name = metadata.get("project_name") or repo_path.name

    return {
        "package_name": package_name,
        "metadata": metadata,
        "current_stage": "extract_metadata",
        "status": "metadata extracted",
    }


def route_after_metadata_extraction(state: AgentState) -> str:
    """Route after metadata extraction."""
    if state["status"] == "failed":
        return "metadata_extraction_failed"

    return "check_metadata"


def metadata_extraction_failed(state: AgentState) -> dict:
    """Stop when project metadata could not be extracted."""
    return {
        "current_stage": "metadata_extraction_failed",
        "status": "metadata extraction failed",
        "needs_human": True,
    }


def check_metadata(state: AgentState) -> dict:
    """Check whether the extracted metadata is sufficient to continue."""
    if not state.get("package_name"):
        status = "missing"
    elif not state.get("build_system"):
        status = "missing"
    else:
        status = "complete"

    return {
        "current_stage": "check_metadata",
        "status": status,
    }


def route_after_metadata_check(state: AgentState) -> str:
    """Route after checking extracted metadata."""
    if state["status"] == "missing":
        return "missing_metadata"

    return "check_existing_spack_package"


def missing_metadata(state: AgentState) -> dict:
    """Stop when required project metadata is missing."""
    return {
        "current_stage": "missing_metadata",
        "status": "missing required metadata",
        "needs_human": True,
    }


def check_existing_spack_package(state: AgentState) -> dict:
    """Check whether the package already exists in Spack's builtin repository."""
    package_name = state["package_name"]
    spack_package_name = _spack_python_name(package_name)

    result = subprocess.run(
        ["spack", "info", f"builtin.{spack_package_name}"],
        capture_output=True,
        text=True,
    )

    mode = "benchmark" if result.returncode == 0 else "new_package"

    return {
        "mode": mode,
        "current_stage": "check_existing_spack_package",
        "status": "existing package found" if mode == "benchmark" else "package not found",
    }


def route_after_spack_package_check(state: AgentState) -> str:
    """Route according to whether an existing Spack package was found."""
    if state["mode"] == "benchmark":
        return "benchmark"

    return "new_package"


def check_pypi_applicability(state: AgentState) -> dict:
    """Check whether PyPI source resolution applies to this project."""
    applicable = (
        "python" in state.get("languages", [])
        and bool(state.get("package_name"))
    )

    return {
        "current_stage": "check_pypi_applicability",
        "status": "applicable" if applicable else "not applicable",
    }


def route_after_pypi_applicability(state: AgentState) -> str:
    """Route to PyPI or repository source resolution."""
    if state["status"] == "applicable":
        return "resolve_pypi_source"

    return "resolve_repository_source"


def resolve_pypi_source(state: AgentState) -> dict:
    """Resolve the package source distribution from PyPI."""
    metadata = dict(state["metadata"])
    project_name = metadata.get("project_name") or state["package_name"]

    if not project_name:
        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": "failed",
            "errors": state["errors"] + ["Missing package name for PyPI lookup"],
        }

    pypi_json_url = f"https://pypi.org/pypi/{project_name}/json"

    try:
        response = requests.get(pypi_json_url, timeout=20)

        if response.status_code == 404:
            return {
                "metadata": metadata,
                "current_stage": "resolve_pypi_source",
                "status": "unavailable",
            }

        response.raise_for_status()
        pypi_data = response.json()
    except (requests.RequestException, ValueError) as error:
        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }

    requested_version = metadata.get("project_version")
    pypi_version = pypi_data.get("info", {}).get("version")
    version = requested_version or pypi_version

    release_files = pypi_data.get("releases", {}).get(version, [])
    sdists = [
        file
        for file in release_files
        if file.get("packagetype") == "sdist"
    ]

    if not sdists:
        if version:
            metadata["source_version"] = str(version)

        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": "unavailable",
        }

    sdist = sdists[0]
    source_url = sdist["url"]
    filename = sdist["filename"]
    source_version = str(version)

    filename_stem = filename

    for suffix in [".tar.gz", ".zip", ".tar.bz2", ".tgz"]:
        filename_stem = filename_stem.removesuffix(suffix)

    version_suffix = f"-{source_version}"

    if filename_stem.endswith(version_suffix):
        pypi_directory = filename_stem[: -len(version_suffix)]
    else:
        pypi_directory = project_name.replace("-", "_")

    metadata["pypi_name"] = pypi_data.get("info", {}).get("name")
    metadata["source_version"] = version
    metadata["pypi_source_url"] = source_url
    metadata["source_sha256"] = sdist.get("digests", {}).get("sha256")
    metadata["source_filename"] = filename
    metadata["pypi_path"] = f"{pypi_directory}/{filename}"
    metadata["source_type"] = "pypi"
    metadata["source_location"] = metadata["pypi_path"]

    return {
        "metadata": metadata,
        "current_stage": "resolve_pypi_source",
        "status": "resolved",
    }


def route_after_pypi_resolution(state: AgentState) -> str:
    """Route after PyPI source resolution."""
    metadata = state.get("metadata", {})

    if (
        state["status"] == "resolved"
        and metadata.get("source_type") == "pypi"
        and metadata.get("source_location")
        and metadata.get("source_version")
        and metadata.get("source_sha256")
    ):
        return "derive_recipe_model"

    if state["status"] == "unavailable":
        return "resolve_repository_source"

    return "pypi_resolution_failed"


def pypi_resolution_failed(state: AgentState) -> dict:
    """Stop when a usable PyPI source could not be resolved."""
    return {
        "current_stage": "pypi_resolution_failed",
        "status": "PyPI source resolution failed",
        "needs_human": True,
    }


def resolve_repository_source(state: AgentState) -> dict:
    """Resolve a source archive from a repository release tag."""
    metadata = dict(state["metadata"])
    version = metadata.get("source_version") or metadata.get("project_version")

    if not version:
        return {
            "metadata": metadata,
            "current_stage": "resolve_repository_source",
            "status": "unresolved",
            "errors": state["errors"] + ["No version available for repository source lookup"],
        }

    try:
        matching_tags = _find_matching_repository_tags(
            state["repo_url"],
            str(version),
        )
    except RuntimeError as error:
        return {
            "metadata": metadata,
            "current_stage": "resolve_repository_source",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }

    if len(matching_tags) != 1:
        return {
            "metadata": metadata,
            "current_stage": "resolve_repository_source",
            "status": "unresolved",
            "errors": state["errors"]
            + [f"Expected one matching repository tag, found {len(matching_tags)}"],
        }

    tag = matching_tags[0]
    repository_url = state["repo_url"].rstrip("/").removesuffix(".git")
    archive_url = f"{repository_url}/archive/refs/tags/{tag}.tar.gz"

    try:
        response = requests.get(archive_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as error:
        return {
            "metadata": metadata,
            "current_stage": "resolve_repository_source",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }

    sha256 = hashlib.sha256(response.content).hexdigest()

    metadata["repository_source_tag"] = tag
    metadata["source_type"] = "url"
    metadata["source_location"] = archive_url
    metadata["source_version"] = str(version)
    metadata["source_sha256"] = sha256

    return {
        "metadata": metadata,
        "current_stage": "resolve_repository_source",
        "status": "resolved",
    }


def route_after_repository_resolution(state: AgentState) -> str:
    """Route after repository source resolution."""
    if state["status"] == "resolved":
        return "derive_recipe_model"

    if state["status"] == "failed":
        return "repository_resolution_failed"

    return "repository_source_unresolved"


def repository_source_unresolved(state: AgentState) -> dict:
    """Stop when a trustworthy repository source cannot be resolved."""
    return {
        "current_stage": "repository_source_unresolved",
        "status": "repository source unresolved",
        "needs_human": True,
    }


def repository_resolution_failed(state: AgentState) -> dict:
    """Stop when repository source resolution fails."""
    return {
        "current_stage": "repository_resolution_failed",
        "status": "repository source resolution failed",
        "needs_human": True,
    }


def _normalize_license(license_data) -> str | None:
    if isinstance(license_data, str):
        return license_data

    if isinstance(license_data, dict):
        return license_data.get("text") or license_data.get("file")

    return None


def _read_dynamic_version(repo_path: Path, pyproject: dict) -> str | None:
    dynamic_config = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("dynamic", {})
    )
    version_config = dynamic_config.get("version", {})

    attr = version_config.get("attr")
    if not attr:
        return None

    module_path, variable_name = attr.rsplit(".", 1)

    package_dir = (
        pyproject.get("tool", {})
        .get("setuptools", {})
        .get("package-dir", {})
        .get("", "")
    )

    base_dirs = [repo_path]
    if package_dir:
        base_dirs.insert(0, repo_path / package_dir)

    relative_module_file = Path(*module_path.split(".")).with_suffix(".py")

    for base_dir in base_dirs:
        candidate = base_dir / relative_module_file

        if not candidate.exists():
            continue

        content = candidate.read_text(encoding="utf-8")
        match = re.search(
            rf'^{re.escape(variable_name)}\s*=\s*["\']([^"\']+)["\']',
            content,
            flags=re.MULTILINE,
        )

        if match:
            return match.group(1)

    return None


def _spack_python_name(name: str) -> str:
    normalized = name.lower().replace("_", "-")

    if normalized.startswith("py-"):
        return normalized

    return f"py-{normalized}"


def _find_matching_repository_tags(repo_url: str, version: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", repo_url],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to read repository tags")

    expected_tags = {
        version,
        f"v{version}",
        f"release-{version}",
    }

    matches = []

    for line in result.stdout.splitlines():
        if not line.strip():
            continue

        _, ref = line.split(maxsplit=1)
        tag = ref.removeprefix("refs/tags/")

        if tag in expected_tags:
            matches.append(tag)

    return matches
