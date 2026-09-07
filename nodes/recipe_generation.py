from pathlib import Path

from state import AgentState


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
        "score": 3,
        "metadata": metadata,
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