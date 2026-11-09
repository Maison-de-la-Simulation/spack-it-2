import argparse
import json
import logging
from pathlib import Path
from output_paths import metadata_output_path, recipe_output_path
from graph import graph


def to_spack_python_package_name(package_name: str) -> str:
    normalized = package_name.lower().replace("_", "-")
    if normalized.startswith("py-"):
        return normalized
    return f"py-{normalized}"


def write_output(final_state: dict) -> None:
    package_name = final_state.get("package_name") or "unknown-package"
    spack_package_name = to_spack_python_package_name(package_name)

    recipe_path = recipe_output_path(spack_package_name)
    metadata_path = metadata_output_path(spack_package_name)

    if (recipe_path.exists() or metadata_path.exists()) and not final_state.get("output_prepared"):
        print("Final status:", final_state.get("status"))
        print("Existing output preserved for:", spack_package_name)
        for error in final_state.get("errors", []):
            print("Error:", error)
        return

    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "repo_url": final_state.get("repo_url"),
        "repo_path": final_state.get("repo_path"),
        "package_name": final_state.get("package_name"),
        "spack_package_name": spack_package_name,
        "languages": final_state.get("languages", []),
        "build_system": final_state.get("build_system"),
        "metadata": final_state.get("metadata", {}),
        "recipe_model": final_state.get("recipe_model"),
        "validation_result": final_state.get("validation_result"),
        "validation": final_state.get("validation", {}),
        "validation_history": final_state.get("validation_history", []),
        "repair_attempts": final_state.get("repair_attempts", 0),
        "quality_score": final_state.get("quality_score"),
        "current_stage": final_state.get("current_stage"),
        "node_history": final_state.get("node_history", []),
        "status": final_state.get("status"),
        "needs_human": final_state.get("needs_human", False),
        "errors": final_state.get("errors", []),
    }

    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(output_data, file, indent=2)

    print("Final status:", final_state.get("status"))
    print("Current stage:", final_state.get("current_stage"))
    print("Node history:", final_state.get("node_history", []))
    print("Package name:", final_state.get("package_name"))
    print("Spack package name:", spack_package_name)
    print("Validation result:", final_state.get("validation_result"))
    print("Quality score (%) (placeholder):", final_state.get("quality_score"))
    print("Metadata written to:", metadata_path)


def run_package(
    repo_url: str,
    remaining_depth: int,
    selected_llm: str,
    overwrite_output: bool = False,
) -> bool:
    final_state = graph.invoke(
        {
            "repo_url": repo_url,
            "remaining_depth": remaining_depth,
            "dependency_path": [],
            "processed_packages": [],
            "selected_llm": selected_llm,
            "overwrite_output": overwrite_output,
        }
    )

    if final_state.get("output_cancelled"):
        print("Run cancelled. Final metadata was not written.")
        return False

    write_output(final_state)
    return final_state.get("status") == "recipe valid"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-L",
        "--depth",
        type=int,
        default=0,
        help="Maximum recursive dependency depth",
    )
    parser.add_argument(
        "--select-llm",
        choices=["mdls", "open-router"],
        default="mdls",
        help="Select the LLM to use",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed workflow logs",
    )

    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Replace existing recipe and metadata files without asking",
    )
    parser.add_argument("repo_url")
    args = parser.parse_args()

    if args.depth < 0:
        parser.error("-L must be zero or greater")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    success = run_package(
        repo_url=args.repo_url,
        remaining_depth=args.depth,
        selected_llm=args.select_llm,
        overwrite_output=args.yes
    )

    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
