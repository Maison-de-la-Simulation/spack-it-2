import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlparse

import requests
from packaging.requirements import InvalidRequirement, Requirement

from llm import decide_optional_group
from state import AgentState


IGNORED_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _repo_name_from_url(repo_url: str) -> str:
    path = urlparse(repo_url).path.rstrip("/")
    name = Path(path).name
    return name.removesuffix(".git")


def _normalize_license(license_data) -> str | None:
    """Keep the upstream license declaration in a consistent string form.

    This does not try to infer an SPDX identifier. A license file name or
    free-form declaration may still require review later.
    """
    if isinstance(license_data, str):
        return license_data

    if isinstance(license_data, dict):
        return license_data.get("text") or license_data.get("file")

    return None


def _read_dynamic_version(repo_path: Path, pyproject: dict) -> str | None:
    """Read a setuptools dynamic version without importing the project.

    Importing an unknown repository could execute project code or fail because
    its dependencies are not installed. Reading a literal assignment keeps
    metadata extraction isolated from the package runtime.
    """
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
    """Clone the repository into the local inspection workspace."""
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
        # The current workflow only inspects the checked-out source tree, so
        # downloading the full Git history would add time without adding evidence.
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
    """Collect enough repository structure for project detection.

    Only a bounded sample is stored in the graph state so that later nodes,
    including future LLM nodes, do not receive an unnecessarily large file list.
    """
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
    # The complete count is retained separately; this sample is only evidence
    # for lightweight language and build-system detection.
    metadata["sample_files"] = files[:100]

    return {
        "metadata": metadata,
        "current_stage": "inspect_files",
        "status": "files inspected",
    }


def detect_project_type(state: AgentState) -> dict:
    """Infer the languages and primary build system from repository files.

    This is deliberately a cheap heuristic. A later stage can review mixed or
    non-standard projects instead of making repository inspection expensive.
    """
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
    """Extract declared project metadata before making Spack-specific decisions.

    This node records upstream evidence as it appears in ``pyproject.toml``.
    Naming dependencies, introducing variants, and choosing Spack constraints
    belong to the recipe-model stage rather than metadata extraction.
    """
    repo_path = Path(state["repo_path"])
    metadata = dict(state["metadata"])

    pyproject_path = repo_path / "pyproject.toml"

    if pyproject_path.exists():
        with pyproject_path.open("rb") as file:
            pyproject = tomllib.load(file)

        project = pyproject.get("project", {})
        build_system = pyproject.get("build-system", {})
        urls = project.get("urls", {})

        # Prefer the standard PEP 621 value. The setuptools-specific lookup is
        # only a fallback for projects that declare the version as dynamic.
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
    """Resolve a source distribution and checksum from PyPI.

    The repository metadata chooses the version when it provides one. Falling
    back to the current PyPI version allows projects with no local version
    declaration to continue.
    """
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

    # When the repository declares a version, its checksum must come from that
    # release rather than from whichever version happens to be latest on PyPI.
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

    # Spack's ``pypi`` attribute stores the project-relative archive path,
    # not the complete files.pythonhosted.org download URL.
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
    """Apply Spack's naming convention for Python packages."""
    normalized = name.lower().replace("_", "-")

    if normalized.startswith("py-"):
        return normalized

    return f"py-{normalized}"

def _spack_version_from_requirement(requirement: str) -> str:
    """Translate the simple Python bounds currently supported by the prototype.

    Python and Spack do not express every version range in exactly the same way.
    Unsupported operators are therefore left unconstrained rather than being
    converted into a constraint that may be incorrect.
    """

    parsed = Requirement(requirement)
    lower_bound = None

    for specifier in parsed.specifier:
        if specifier.operator == "==":
            return f"@={specifier.version}"

        if specifier.operator == ">=":
            lower_bound = specifier.version

    if lower_bound:
        return f"@{lower_bound}:"

    return ""


def _dependency_model(
    requirement: str,
    dependency_types: tuple[str, ...],
    when: str | None = None,
) -> dict:
    """Convert upstream dependency evidence into a structured Spack decision.

    ``source_requirement`` is retained so that generated constraints can later
    be traced back to upstream metadata and compared with an existing recipe.
    """

    parsed = Requirement(requirement)

    dependency = {
        "name": _spack_python_name(parsed.name),
        "version": _spack_version_from_requirement(requirement),
        "types": list(dependency_types),
        "source_requirement": requirement,
    }

    if when is not None:
        dependency["when"] = when

    return dependency


def derive_recipe_model(state: AgentState) -> dict:
    """Build the structured data that generate_recipe will render."""
    metadata = state["metadata"]
    package_name = state["package_name"]

    if not package_name:
        return {
            "recipe_model": None,
            "current_stage": "derive_recipe_model",
            "status": "missing package name",
            "needs_human": True,
        }

    if "python" not in state["languages"]:
        return {
            "recipe_model": None,
            "current_stage": "derive_recipe_model",
            "status": "recipe model currently supports Python projects only",
            "needs_human": True,
        }

    required_source_fields = ("pypi_path", "source_version", "source_sha256")
    missing_source_fields = [
        field for field in required_source_fields if not metadata.get(field)
    ]

    if missing_source_fields:
        return {
            "recipe_model": None,
            "current_stage": "derive_recipe_model",
            "status": "source information incomplete",
            "errors": state["errors"]
            + [f"missing source fields: {', '.join(missing_source_fields)}"],
            "needs_human": True,
        }

    spack_package_name = _spack_python_name(package_name)
    class_name = "".join(
        part.capitalize()
        for part in spack_package_name.replace("-", "_").split("_")
    )

    requires_python = metadata.get("requires_python")
    python_version = ""

    try:
        if requires_python:
            python_version = _spack_version_from_requirement(
                f"python{requires_python}"
            )

        dependencies = [
            {
                "name": "python",
                "version": python_version,
                "types": ["build", "run"],
                "source_requirement": requires_python,
            }
        ]

        dependencies.extend(
            _dependency_model(requirement, ("build",))
            for requirement in metadata.get("build_requires", [])
        )

        dependencies.extend(
            _dependency_model(requirement, ("build", "run"))
            for requirement in metadata.get("dependencies", [])
        )

        variants = []
        optional_dependencies = metadata.get("optional_dependencies", {})

        for group_name, requirements in optional_dependencies.items():
            if group_name == "mpi":
                create_variant = True
                confidence = "high"
                reason = "MPI optional group is handled deterministically"
                decision_source = "rule"
            else:
                try:
                    decision = decide_optional_group(
                        package_name=package_name,
                        group_name=group_name,
                        requirements=requirements,
                    )
                except (RuntimeError, ValueError) as error:
                    return {
                        "recipe_model": None,
                        "current_stage": "derive_recipe_model",
                        "status": "LLM optional dependency decision failed",
                        "errors": state["errors"] + [str(error)],
                        "needs_human": True,
                    }

                create_variant = decision["create_variant"]
                confidence = decision["confidence"]
                reason = decision["reason"]
                decision_source = decision["decision_source"]

            if confidence != "high":
                return {
                    "recipe_model": None,
                    "current_stage": "derive_recipe_model",
                    "status": "optional dependency decision needs review",
                    "errors": state["errors"]
                    + [f"{group_name}: {reason}"],
                    "needs_human": True,
                }

            if not create_variant:
                continue

            variants.append(
                {
                    "name": group_name,
                    "default": False,
                    "description": f"Enable {group_name} support",
                    "source": f"project.optional-dependencies.{group_name}",
                    "decision_source": decision_source,
                    "confidence": confidence,
                    "reason": reason,
                }
            )

            dependencies.extend(
                _dependency_model(
                    requirement,
                    ("build", "run"),
                    when=f"+{group_name}",
                )
                for requirement in requirements
            )

    except InvalidRequirement as error:
        return {
            "recipe_model": None,
            "current_stage": "derive_recipe_model",
            "status": "failed to parse dependency requirement",
            "errors": state["errors"] + [str(error)],
            "needs_human": True,
        }

    recipe_model = {
        "package_name": spack_package_name,
        "class_name": class_name,
        "base_class": "PythonPackage",
        "description": metadata.get("description") or package_name,
        "homepage": metadata.get("homepage") or state["repo_url"],
        "license": metadata.get("license") or "UNKNOWN",
        "source": {
            "type": "pypi",
            "pypi_path": metadata["pypi_path"],
            "version": str(metadata["source_version"]),
            "sha256": metadata["source_sha256"],
        },
        "dependencies": dependencies,
        "variants": variants,
    }

    return {
        "recipe_model": recipe_model,
        "current_stage": "derive_recipe_model",
        "status": "recipe model derived",
    }


def _render_dependency(dependency: dict) -> str:
    spec = f'{dependency["name"]}{dependency["version"]}'
    dependency_types = dependency["types"]

    if len(dependency_types) == 1:
        type_value = f'"{dependency_types[0]}"'
    else:
        type_value = "(" + ", ".join(
            f'"{dependency_type}"'
            for dependency_type in dependency_types
        ) + ")"

    arguments = [
        f'"{spec}"',
        f"type={type_value}",
    ]

    if dependency.get("when"):
        arguments.append(f'when="{dependency["when"]}"')

    return f'    depends_on({", ".join(arguments)})'


def generate_recipe(state: AgentState) -> dict:
    """Render package.py from the recipe model."""
    recipe_model = state["recipe_model"]

    if not recipe_model:
        return {
            "current_stage": "generate_recipe",
            "status": "recipe model missing",
            "needs_human": True,
        }

    spack_package_name = recipe_model["package_name"]
    spack_package_dir = spack_package_name.replace("-", "_")
    source = recipe_model["source"]

    output_dir = Path("outputs") / spack_package_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = output_dir / "package.py"

    recipe = f'''# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class {recipe_model["class_name"]}({recipe_model["base_class"]}):
    """{recipe_model["description"]}."""

    homepage = "{recipe_model["homepage"]}"
    pypi = "{source["pypi_path"]}"

    license("{recipe_model["license"]}")
    version("{source["version"]}", sha256="{source["sha256"]}")

'''

    for variant in recipe_model["variants"]:
        recipe += (
            f'    variant("{variant["name"]}", '
            f'default={variant["default"]}, '
            f'description="{variant["description"]}")\n'
        )

    if recipe_model["variants"]:
        recipe += "\n"

    for dependency in recipe_model["dependencies"]:
        recipe += _render_dependency(dependency) + "\n"

    recipe_path.write_text(recipe, encoding="utf-8")

    metadata = dict(state["metadata"])
    metadata["generated_recipe_path"] = str(recipe_path)

    return {
        "current_stage": "generate_recipe",
        "status": "recipe generated",
        "score": 3,
        "metadata": metadata,
    }


def route_after_recipe_model(state: AgentState) -> str:
    if state["needs_human"] or not state["recipe_model"]:
        return "human_review"

    return "ready_for_recipe"


def route_after_metadata(state: AgentState) -> str:
    """Choose whether deterministic recipe processing can continue.

    ``unsupported`` is reserved for project types outside the current scope.
    ``missing_metadata`` means required evidence is absent. ``human_review`` is
    used when an earlier node found information but could not handle it safely.
    """
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

    return "derive_recipe_model"
