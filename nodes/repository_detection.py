import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from state import AgentState

IGNORED_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def validate_url(state: AgentState) -> dict:
    """Validate the input GitHub repository URL."""
    repo_url = state["repo_url"].strip()
    parsed = urlparse(repo_url)

    path_parts = [part for part in parsed.path.split("/") if part]

    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.lower() not in {"github.com", "www.github.com"}
        or len(path_parts) != 2
    ):
        return {
            "current_stage": "validate_url",
            "status": "invalid",
        }

    return {
        "repo_url": repo_url.rstrip("/"),
        "current_stage": "validate_url",
        "status": "valid",
    }


def initialize_state(state: AgentState) -> dict:
    """Initialize the shared workflow state."""
    return {
        "repo_path": None,
        "package_name": None,
        "languages": [],
        "build_system": None,
        "mode": None,
        "metadata": {},
        "recipe_model": None,
        "current_stage": "initialize_state",
        "errors": [],
        "needs_human": False,
        "status": "initialized",
    }


def clone_repo(state: AgentState) -> dict:
    """Clone the repository into the local workspace."""
    repo_url = state["repo_url"]
    repo_name = _repo_name_from_url(repo_url)

    workspace = Path("workspace/repos")
    workspace.mkdir(parents=True, exist_ok=True)

    repo_path = workspace / repo_name

    try:
        if repo_path.exists():
            shutil.rmtree(repo_path)

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
        }

    except OSError as error:
        return {
            "current_stage": "clone_repo",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }


def inspect_files(state: AgentState) -> dict:
    """Inspect the repository files for project detection."""
    repo_path = Path(state["repo_path"])

    try:
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

    except OSError as error:
        return {
            "current_stage": "inspect_files",
            "status": "failed",
            "errors": state["errors"] + [str(error)],
        }


def detect_project_type(state: AgentState) -> dict:
    """Detect the project language and build system."""
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

    supported = "python" in languages and build_system == "pyproject"

    return {
        "languages": languages,
        "build_system": build_system,
        "current_stage": "detect_project_type",
        "status": "supported" if supported else "unsupported",
    }


def route_after_validate_url(state: AgentState) -> str:
    """Route after URL validation."""
    if state["status"] == "valid":
        return "initialize_state"

    return "invalid_input"


def invalid_input(state: AgentState) -> dict:
    """Stop when the repository URL is invalid."""
    return {
        "current_stage": "invalid_input",
        "status": "invalid repository URL",
        "errors": ["Invalid GitHub repository URL"],
        "needs_human": True,
    }


def route_after_clone_repo(state: AgentState) -> str:
    """Route after repository cloning."""
    if state["status"] == "failed":
        return "clone_failed"

    return "inspect_files"


def clone_failed(state: AgentState) -> dict:
    """Stop when the repository could not be cloned."""
    return {
        "current_stage": "clone_failed",
        "status": "repository clone failed",
        "needs_human": True,
    }


def route_after_inspect_files(state: AgentState) -> str:
    """Route after repository file inspection."""
    if state["status"] == "failed":
        return "inspection_failed"

    return "detect_project_type"


def inspection_failed(state: AgentState) -> dict:
    """Stop when repository inspection fails."""
    return {
        "current_stage": "inspection_failed",
        "status": "repository inspection failed",
        "needs_human": True,
    }


def route_after_project_detection(state: AgentState) -> str:
    """Route after project type detection."""
    if state["status"] == "supported":
        return "extract_metadata"

    return "unsupported_project"


def unsupported_project(state: AgentState) -> dict:
    """Stop when the detected project type is unsupported."""
    return {
        "current_stage": "unsupported_project",
        "status": "unsupported project type",
        "needs_human": True,
    }


def _repo_name_from_url(repo_url: str) -> str:
    path = urlparse(repo_url).path.rstrip("/")
    name = Path(path).name
    return name.removesuffix(".git")