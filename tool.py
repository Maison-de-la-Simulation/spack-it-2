import json
import sys
from pathlib import Path

from graph import graph


def to_spack_python_package_name(package_name: str) -> str:
    """Normalize an upstream Python project name to its Spack package name."""
    normalized = package_name.lower().replace("_", "-")
    if normalized.startswith("py-"):
        return normalized
    return f"py-{normalized}"


def main() -> None:
    """Run the graph and persist its final state for inspection."""
    if len(sys.argv) != 2:
        print("Usage: ./tool.py <github-repo-url>")
        sys.exit(1)

    repo_url = sys.argv[1]

    initial_state = {
        "repo_url": repo_url,
        "repo_path": None,
        "package_name": None,
        "languages": [],
        "build_system": None,
        "metadata": {},
        "recipe_model": None,
        "current_stage": "start",
        "errors": [],
        "score": 0,
        "attempts": 0,
        "needs_human": False,
        "status": "started",
    }

    final_state = graph.invoke(initial_state)

    package_name = final_state["package_name"] or "unknown-package"
    spack_package_name = to_spack_python_package_name(package_name)

    output_dir = Path("outputs") / spack_package_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Persist the full result even when the workflow stops early. Failure states
    # and extracted evidence will later be inputs to validation and repair.
    output_data = {
        "repo_url": final_state["repo_url"],
        "repo_path": final_state["repo_path"],
        "package_name": final_state["package_name"],
        "spack_package_name": spack_package_name,
        "languages": final_state["languages"],
        "build_system": final_state["build_system"],
        "metadata": final_state["metadata"],
        "recipe_model": final_state["recipe_model"],
        "current_stage": final_state["current_stage"],
        "status": final_state["status"],
        "score": final_state["score"],
        "needs_human": final_state["needs_human"],
        "errors": final_state["errors"],
    }

    metadata_path = output_dir / "metadata.json"

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(output_data, file, indent=2)

    print("Final status:", final_state["status"])
    print("Current stage:", final_state["current_stage"])
    print("Package name:", final_state["package_name"])
    print("Spack package name:", spack_package_name)
    print("Languages:", ", ".join(final_state["languages"]) or "unknown")
    print("Build system:", final_state["build_system"])
    print("Needs human:", final_state["needs_human"])
    print("Score:", final_state["score"])
    print("Metadata written to:", metadata_path)


if __name__ == "__main__":
    main()