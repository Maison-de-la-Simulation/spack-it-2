from packaging.requirements import InvalidRequirement, Requirement

from llm import decide_optional_group
from state import AgentState


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


def route_after_recipe_model(state: AgentState) -> str:
    """Route after recipe model derivation."""
    if state.get("recipe_model"):
        return "check_recipe_inputs"

    if state.get("status") == "optional dependency decision needs review":
        return "recipe_model_ambiguous"

    return "recipe_model_failed"


def recipe_model_ambiguous(state: AgentState) -> dict:
    """Stop when a recipe decision is not confident enough."""
    return {
        "current_stage": "recipe_model_ambiguous",
        "status": "recipe model needs review",
        "needs_human": True,
    }


def recipe_model_failed(state: AgentState) -> dict:
    """Stop when the recipe model cannot be constructed."""
    return {
        "current_stage": "recipe_model_failed",
        "status": "recipe model derivation failed",
        "needs_human": True,
    }


def check_recipe_inputs(state: AgentState) -> dict:
    """Check that recipe generation has all required inputs."""
    recipe_model = state.get("recipe_model")

    if not recipe_model:
        return {
            "current_stage": "check_recipe_inputs",
            "status": "recipe inputs incomplete",
            "needs_human": True,
        }

    required_fields = (
        "package_name",
        "class_name",
        "base_class",
        "description",
        "homepage",
        "license",
        "source",
        "dependencies",
        "variants",
    )

    missing_fields = [
        field for field in required_fields
        if field not in recipe_model
    ]

    source = recipe_model.get("source", {})

    for field in ("pypi_path", "version", "sha256"):
        if not source.get(field):
            missing_fields.append(f"source.{field}")

    if missing_fields:
        return {
            "current_stage": "check_recipe_inputs",
            "status": "recipe inputs incomplete",
            "errors": state["errors"]
            + [f"missing recipe inputs: {', '.join(missing_fields)}"],
            "needs_human": True,
        }

    return {
        "current_stage": "check_recipe_inputs",
        "status": "recipe inputs complete",
    }


def route_after_recipe_inputs(state: AgentState) -> str:
    if state.get("status") == "recipe inputs complete":
        return "generate_recipe"

    return "recipe_inputs_missing"


def recipe_inputs_missing(state: AgentState) -> dict:
    return {
        "current_stage": "recipe_inputs_missing",
        "status": "required recipe inputs missing",
        "needs_human": True,
    }


def _spack_python_name(name: str) -> str:
    normalized = name.lower().replace("_", "-")

    if normalized.startswith("py-"):
        return normalized

    return f"py-{normalized}"


def _spack_version_from_requirement(requirement: str) -> str:
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