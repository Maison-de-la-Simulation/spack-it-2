import re
import subprocess
import tomllib
import requests
from pathlib import Path
from urllib.parse import urlparse

from state import AgentState


IGNORED_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _repo_name_from_url(repo_url: str) -> str:
    path = urlparse(repo_url).path.rstrip("/")
    name = Path(path).name
    return name.removesuffix(".git")


def _normalize_license(license_data) -> str | None:
    if isinstance(license_data, str):
        return license_data

    if isinstance(license_data, dict):
        return license_data.get("text") or license_data.get("file")

    return None


def _read_dynamic_version(repo_path: Path, pyproject: dict) -> str | None:
    dynamic_config = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {})
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


def clone_repo(state: AgentState) -> dict:
    repo_url = state["repo_url"]
    repo_name = _repo_name_from_url(repo_url)

    workspace = Path("workspace/repos")
    workspace.mkdir(parents=True, exist_ok=True)

    repo_path = workspace / repo_name

    if repo_path.exists():
        return {
            "repo_path": str(repo_path),
            "current_stage": "clone_repo",
            "status": "repo already exists",
        }

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return {
            "repo_path": str(repo_path),
            "current_stage": "clone_repo",
            "status": "cloned",
        }
    except subprocess.CalledProcessError as error:
        return {
            "current_stage": "clone_repo",
            "status": "failed",
            "errors": state["errors"] + [error.stderr],
            "needs_human": True,
        }


def inspect_files(state: AgentState) -> dict:
    repo_path = Path(state["repo_path"])

    files = []

    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(repo_path)

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        files.append(str(relative_path))

    metadata = dict(state["metadata"])
    metadata["file_count"] = len(files)
    metadata["top_level_files"] = sorted(
        path.name
        for path in repo_path.iterdir()
        if path.name not in IGNORED_DIRS
    )
    metadata["sample_files"] = files[:100]

    return {
        "metadata": metadata,
        "current_stage": "inspect_files",
        "status": "files inspected",
    }


def detect_project_type(state: AgentState) -> dict:
    repo_path = Path(state["repo_path"])
    files = set(state["metadata"].get("sample_files", []))
    top_level_files = set(state["metadata"].get("top_level_files", []))

    languages = []

    if any(file.endswith(".py") for file in files) or {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
    } & top_level_files:
        languages.append("python")

    if any(file.endswith((".c", ".h")) for file in files):
        languages.append("c")

    if any(file.endswith((".cc", ".cpp", ".cxx", ".hpp", ".hh")) for file in files):
        languages.append("c++")

    build_system = None

    if (repo_path / "pyproject.toml").exists():
        build_system = "pyproject"
    elif (repo_path / "setup.py").exists():
        build_system = "setuptools"
    elif (repo_path / "CMakeLists.txt").exists():
        build_system = "cmake"
    elif (repo_path / "meson.build").exists():
        build_system = "meson"

    status = "supported" if set(languages) <= {"python", "c", "c++"} else "unsupported"

    return {
        "languages": languages,
        "build_system": build_system,
        "current_stage": "detect_project_type",
        "status": status,
    }


def extract_metadata(state: AgentState) -> dict:
    repo_path = Path(state["repo_path"])
    metadata = dict(state["metadata"])

    pyproject_path = repo_path / "pyproject.toml"

    if pyproject_path.exists():
        with pyproject_path.open("rb") as file:
            pyproject = tomllib.load(file)

        project = pyproject.get("project", {})
        build_system = pyproject.get("build-system", {})
        urls = project.get("urls", {})

        project_version = project.get("version")
        dynamic_version = _read_dynamic_version(repo_path, pyproject)

        metadata["project_name"] = project.get("name")
        metadata["description"] = project.get("description")
        metadata["project_version"] = project_version or dynamic_version
        metadata["version_source"] = "project.version" if project_version else "dynamic"
        metadata["dynamic_fields"] = project.get("dynamic", [])
        metadata["requires_python"] = project.get("requires-python")
        metadata["license"] = _normalize_license(project.get("license"))
        metadata["homepage"] = urls.get("Homepage") or urls.get("homepage")
        metadata["source_url"] = urls.get("Source") or urls.get("source")
        metadata["dependencies"] = project.get("dependencies", [])
        metadata["optional_dependencies"] = project.get("optional-dependencies", {})
        metadata["build_backend"] = build_system.get("build-backend")
        metadata["build_requires"] = build_system.get("requires", [])

    package_name = metadata.get("project_name") or _repo_name_from_url(state["repo_url"])

    return {
        "package_name": package_name,
        "metadata": metadata,
        "current_stage": "extract_metadata",
        "status": "metadata extracted",
        "score": 1,
    }

def resolve_pypi_source(state: AgentState) -> dict:
    metadata = dict(state["metadata"])
    project_name = metadata.get("project_name") or state["package_name"]

    if not project_name:
        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": "missing package name",
            "needs_human": True,
        }

    pypi_json_url = f"https://pypi.org/pypi/{project_name}/json"

    try:
        response = requests.get(pypi_json_url, timeout=20)
        response.raise_for_status()
        pypi_data = response.json()
    except requests.RequestException as error:
        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": "failed to fetch PyPI metadata",
            "errors": state["errors"] + [str(error)],
            "needs_human": True,
        }

    requested_version = metadata.get("project_version")
    pypi_version = pypi_data.get("info", {}).get("version")
    version = requested_version or pypi_version

    release_files = pypi_data.get("releases", {}).get(version, [])
    sdists = [file for file in release_files if file.get("packagetype") == "sdist"]

    if not sdists:
        return {
            "metadata": metadata,
            "current_stage": "resolve_pypi_source",
            "status": f"no source distribution found on PyPI for version {version}",
            "needs_human": True,
        }

    sdist = sdists[0]
    source_url = sdist["url"]
    filename = sdist["filename"]

    # Example PyPI URL:
    # https://files.pythonhosted.org/packages/source/d/deisa_dask/deisa_dask-0.6.0.tar.gz
    # Spack pypi path should be:
    # deisa_dask/deisa_dask-0.6.0.tar.gz
    source_version = str(version)
    filename_stem = filename

    for suffix in [".tar.gz", ".zip", ".tar.bz2", ".tgz"]:
        filename_stem = filename_stem.removesuffix(suffix)

    normalized_version_suffix = f"-{source_version}"
    if filename_stem.endswith(normalized_version_suffix):
        pypi_directory = filename_stem[: -len(normalized_version_suffix)]
    else:
        pypi_directory = project_name.replace("-", "_")

    pypi_path = f"{pypi_directory}/{filename}"

    metadata["pypi_name"] = pypi_data.get("info", {}).get("name")
    metadata["source_version"] = version
    metadata["pypi_source_url"] = source_url
    metadata["source_sha256"] = sdist.get("digests", {}).get("sha256")
    metadata["source_filename"] = filename
    metadata["pypi_path"] = pypi_path

    return {
        "metadata": metadata,
        "current_stage": "resolve_pypi_source",
        "status": "PyPI source resolved",
        "score": 2,
    }

def _spack_python_name(name: str) -> str:
    normalized = name.lower().replace("_", "-")
    if normalized.startswith("py-"):
        return normalized
    return f"py-{normalized}"


def _spack_version_from_requirement(requirement: str) -> str:
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return ""

    parsed = Requirement(requirement)
    lower_bound = None
    upper_bound = None

    for specifier in parsed.specifier:
        if specifier.operator in {">=", "=="}:
            lower_bound = specifier.version
        elif specifier.operator == "<":
            upper_bound = specifier.version

    if lower_bound and upper_bound:
        return f"@{lower_bound}:{upper_bound}"
    if lower_bound:
        return f"@{lower_bound}:"
    return ""


def _dependency_line(requirement: str) -> str:
    from packaging.requirements import Requirement

    parsed = Requirement(requirement)
    spack_name = _spack_python_name(parsed.name)
    version_constraint = _spack_version_from_requirement(requirement)

    return f'    depends_on("{spack_name}{version_constraint}", type=("build", "run"))'


def _build_dependency_line(requirement: str) -> str:
    from packaging.requirements import Requirement

    parsed = Requirement(requirement)
    spack_name = _spack_python_name(parsed.name)
    version_constraint = _spack_version_from_requirement(requirement)

    return f'    depends_on("{spack_name}{version_constraint}", type="build")'


def generate_recipe(state: AgentState) -> dict:
    metadata = state["metadata"]
    package_name = state["package_name"]
    spack_package_name = _spack_python_name(package_name)

    class_name = "".join(part.capitalize() for part in spack_package_name.replace("-", "_").split("_"))

    output_dir = Path("outputs") / spack_package_name
    output_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = output_dir / "package.py"

    requires_python = metadata.get("requires_python", "")

    if requires_python.startswith(">="):
        python_constraint = f"@{requires_python.removeprefix('>=')}:"
    else:
        python_constraint = "@3.10:"

    build_dependencies = [
        _build_dependency_line(requirement)
        for requirement in metadata.get("build_requires", [])
    ]

    runtime_dependencies = [
        _dependency_line(requirement)
        for requirement in metadata.get("dependencies", [])
    ]

    optional_dependencies = metadata.get("optional_dependencies", {})
    variant_lines = []
    optional_dependency_lines = []

    if "mpi" in optional_dependencies:
        variant_lines.append('    variant("mpi", default=False, description="Enable MPI support")')
        optional_dependency_lines.append('    depends_on("mpi", when="+mpi")')
        optional_dependency_lines.append('    depends_on("py-mpi4py", type=("build", "run"), when="+mpi")')

    recipe = f'''# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class {class_name}(PythonPackage):
    """{metadata.get("description") or package_name}."""

    homepage = "{metadata.get("homepage") or state["repo_url"]}"
    pypi = "{metadata["pypi_path"]}"

    license("{metadata.get("license") or "UNKNOWN"}")

    version("{metadata["source_version"]}", sha256="{metadata["source_sha256"]}")

'''

    if variant_lines:
        recipe += "\n".join(variant_lines) + "\n\n"

    recipe += f'    depends_on("python{python_constraint}", type=("build", "run"))\n'

    for line in build_dependencies:
        recipe += line + "\n"

    recipe += "\n"

    for line in runtime_dependencies:
        recipe += line + "\n"

    if optional_dependency_lines:
        recipe += "\n"
        for line in optional_dependency_lines:
            recipe += line + "\n"

    recipe_path.write_text(recipe, encoding="utf-8")

    return {
        "current_stage": "generate_recipe",
        "status": "recipe generated",
        "score": 3,
        "metadata": metadata | {"generated_recipe_path": str(recipe_path)},
    }

def route_after_metadata(state: AgentState) -> str:
    if state["needs_human"]:
        return "human_review"

    if not state["languages"]:
        return "unsupported"

    if not set(state["languages"]) <= {"python", "c", "c++"}:
        return "unsupported"

    if state["build_system"] is None:
        return "missing_metadata"

    if not state["metadata"].get("source_sha256"):
        return "missing_metadata"

    return "ready_for_recipe"
