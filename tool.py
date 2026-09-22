import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from graph import graph


def to_spack_python_package_name(package_name: str) -> str:
    normalized = package_name.lower().replace("_", "-")
    if normalized.startswith("py-"):
        return normalized
    return f"py-{normalized}"


def write_output(final_state: dict) -> None:
    package_name = final_state.get("package_name") or "unknown-package"
    spack_package_name = to_spack_python_package_name(package_name)
    spack_package_dir = spack_package_name.replace("-", "_")

    output_dir = Path("outputs") / spack_package_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_data = {
        "repo_url": final_state.get("repo_url"),
        "repo_path": final_state.get("repo_path"),
        "package_name": final_state.get("package_name"),
        "spack_package_name": spack_package_name,
        "languages": final_state.get("languages", []),
        "build_system": final_state.get("build_system"),
        "mode": final_state.get("mode"),
        "metadata": final_state.get("metadata", {}),
        "recipe_model": final_state.get("recipe_model"),
        "current_stage": final_state.get("current_stage"),
        "status": final_state.get("status"),
        "needs_human": final_state.get("needs_human", False),
        "errors": final_state.get("errors", []),
    }

    metadata_path = output_dir / "metadata.json"

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(output_data, file, indent=2)

    print("Final status:", final_state.get("status"))
    print("Current stage:", final_state.get("current_stage"))
    print("Package name:", final_state.get("package_name"))
    print("Spack package name:", spack_package_name)
    print("Mode:", final_state.get("mode"))
    print("Metadata written to:", metadata_path)


def spack_package_exists(package_name: str) -> bool:
    result = subprocess.run(
        ["spack", "info", f"builtin.{package_name}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_missing_dependencies(final_state: dict) -> list[str]:
    recipe_model = final_state.get("recipe_model") or {}
    dependencies = recipe_model.get("dependencies", [])

    missing = []

    for dependency in dependencies:
        name = dependency.get("name")

        if not name or name == "python":
            continue

        if not spack_package_exists(name):
            missing.append(name)

    return sorted(set(missing))


def resolve_dependency_source(spack_name: str) -> str | None:
    pypi_name = spack_name.removeprefix("py-")

    try:
        response = requests.get(
            f"https://pypi.org/pypi/{pypi_name}/json",
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

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

        return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}"

    return None


def run_package(
    repo_url: str,
    remaining_depth: int,
    processed_packages: set[str],
    dependency_path: list[str],
) -> bool:
    final_state = graph.invoke({"repo_url": repo_url})
    write_output(final_state)

    if final_state.get("status") != "recipe generated":
        return False

    package_name = final_state.get("package_name")

    if not package_name:
        return False

    spack_package_name = to_spack_python_package_name(package_name)

    if spack_package_name in dependency_path:
        print("Dependency cycle detected:", " -> ".join(
            dependency_path + [spack_package_name]
        ))
        return False

    processed_packages.add(spack_package_name)

    if remaining_depth <= 0:
        return True

    missing_dependencies = check_missing_dependencies(final_state)

    for dependency_name in missing_dependencies:
        if dependency_name in processed_packages:
            continue

        dependency_repo = resolve_dependency_source(dependency_name)

        if not dependency_repo:
            print(
                f"Could not resolve upstream repository for "
                f"{dependency_name}"
            )
            return False

        print()
        print("Missing dependency:", dependency_name)
        print("Repository:", dependency_repo)
        print("Remaining depth:", remaining_depth - 1)

        success = run_package(
            dependency_repo,
            remaining_depth - 1,
            processed_packages,
            dependency_path + [spack_package_name],
        )

        if not success:
            print("Failed to package dependency:", dependency_name)
            return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-L",
        "--depth",
        type=int,
        default=0,
        help="Maximum recursive dependency depth",
    )
    parser.add_argument("repo_url")

    args = parser.parse_args()

    if args.depth < 0:
        parser.error("-L must be zero or greater")

    success = run_package(
        repo_url=args.repo_url,
        remaining_depth=args.depth,
        processed_packages=set(),
        dependency_path=[],
    )

    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()