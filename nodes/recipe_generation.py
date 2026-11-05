from pathlib import Path
from output_paths import metadata_output_path, recipe_output_path
from state import AgentState


def prepare_output(state: AgentState) -> dict:
    """Ask before replacing output from an earlier run."""
    package_name = state["recipe_model"]["package_name"]
    recipe_path = recipe_output_path(package_name)
    metadata_path = metadata_output_path(package_name)

    if recipe_path.exists() or metadata_path.exists():
        answer = input(
            f"Output for {package_name} already exists. "
            "Replace package.py and metadata.json? [y/N]: "
        )

        if answer.strip().lower() != "y":
            return {
                "current_stage": "prepare_output",
                "status": "output cancelled",
                "output_prepared": False,
                "output_cancelled": True,
                "needs_human": False,
            }

    for output_file in (recipe_path, metadata_path):
        if output_file.is_file():
            output_file.unlink()

    return {
        "current_stage": "prepare_output",
        "status": "output prepared",
        "output_prepared": True,
        "output_cancelled": False,
        "needs_human": False,
    }


def route_after_output_preparation(state: AgentState) -> str:
    if state["output_cancelled"]:
        return "end"

    return "check_missing_dependencies"


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
    source = recipe_model["source"]
    if source["type"] == "pypi":
        source_line = f'    pypi = "{source["location"]}"'
    elif source["type"] == "url":
        source_line = f'    url = "{source["location"]}"'
    else:
        return {
            "current_stage": "generate_recipe",
            "status": "unsupported source type",
            "needs_human": True,
        }

    recipe_path = recipe_output_path(spack_package_name)
    recipe_path.parent.mkdir(parents=True, exist_ok=True)

    recipe = f'''# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class {recipe_model["class_name"]}({recipe_model["base_class"]}):
    """{recipe_model["description"]}."""

    homepage = "{recipe_model["homepage"]}"
{source_line}

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
        "metadata": metadata,
    }


def route_after_recipe_generation(state: AgentState) -> str:
    """Route after recipe generation."""
    if state["status"] == "recipe generated":
        if state.get("dependency_path"):
            return "end"
        return "prepare_validation"

    return "end"


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