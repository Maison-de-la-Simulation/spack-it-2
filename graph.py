from langgraph.graph import END, START, StateGraph

from nodes.metadata_resolution import (
    check_existing_spack_package,
    check_metadata,
    check_pypi_applicability,
    extract_metadata,
    metadata_extraction_failed,
    missing_metadata,
    pypi_resolution_failed,
    repository_resolution_failed,
    repository_source_unresolved,
    resolve_pypi_source,
    resolve_repository_source,
    route_after_metadata_check,
    route_after_metadata_extraction,
    route_after_pypi_applicability,
    route_after_pypi_resolution,
    route_after_repository_resolution,
    route_after_spack_package_check,
)

from nodes.recipe_generation import generate_recipe

from nodes.recipe_model import (
    check_recipe_inputs,
    derive_recipe_model,
    recipe_inputs_missing,
    recipe_model_ambiguous,
    recipe_model_failed,
    route_after_recipe_inputs,
    route_after_recipe_model,
)

from nodes.repository_detection import (
    clone_failed,
    clone_repo,
    detect_project_type,
    initialize_state,
    inspect_files,
    inspection_failed,
    invalid_input,
    route_after_clone_repo,
    route_after_inspect_files,
    route_after_project_detection,
    route_after_validate_url,
    unsupported_project,
    validate_url,
)
from state import AgentState


def build_graph():
    """Build the workflow while keeping extraction, routing, and rendering separate."""
    workflow = StateGraph(AgentState)

    # Section 1: Repository and Project Detection
    workflow.add_node("validate_url", validate_url)
    workflow.add_node("initialize_state", initialize_state)
    workflow.add_node("clone_repo", clone_repo)
    workflow.add_node("inspect_files", inspect_files)
    workflow.add_node("detect_project_type", detect_project_type)

    workflow.add_node("invalid_input", invalid_input)
    workflow.add_node("clone_failed", clone_failed)
    workflow.add_node("inspection_failed", inspection_failed)
    workflow.add_node("unsupported_project", unsupported_project)

    # Section 2
    workflow.add_node("extract_metadata", extract_metadata)
    workflow.add_node("metadata_extraction_failed", metadata_extraction_failed)
    workflow.add_node("check_metadata", check_metadata)
    workflow.add_node("missing_metadata", missing_metadata)

    workflow.add_node(
        "check_existing_spack_package",
        check_existing_spack_package,
    )
    workflow.add_node(
        "check_pypi_applicability",
        check_pypi_applicability,
    )
    workflow.add_node("resolve_pypi_source", resolve_pypi_source)
    workflow.add_node("pypi_resolution_failed", pypi_resolution_failed)

    workflow.add_node("resolve_repository_source", resolve_repository_source)
    workflow.add_node(
        "repository_source_unresolved",
        repository_source_unresolved,
    )

    workflow.add_node(
        "repository_resolution_failed",
        repository_resolution_failed,
    )

    workflow.add_node("derive_recipe_model", derive_recipe_model)
    workflow.add_node("recipe_model_ambiguous", recipe_model_ambiguous)
    workflow.add_node("recipe_model_failed", recipe_model_failed)
    workflow.add_node("check_recipe_inputs", check_recipe_inputs)
    workflow.add_node("recipe_inputs_missing", recipe_inputs_missing)

    # Section 3
    workflow.add_node("generate_recipe", generate_recipe)

    # Section 1: Repository and Project Detection

    workflow.add_edge(START, "validate_url")

    workflow.add_conditional_edges(
        "validate_url",
        route_after_validate_url,
        {
            "initialize_state": "initialize_state",
            "invalid_input": "invalid_input",
        },
    )

    workflow.add_edge("initialize_state", "clone_repo")

    workflow.add_conditional_edges(
        "clone_repo",
        route_after_clone_repo,
        {
            "inspect_files": "inspect_files",
            "clone_failed": "clone_failed",
        },
    )

    workflow.add_conditional_edges(
        "inspect_files",
        route_after_inspect_files,
        {
            "detect_project_type": "detect_project_type",
            "inspection_failed": "inspection_failed",
        },
    )

    workflow.add_conditional_edges(
        "detect_project_type",
        route_after_project_detection,
        {
            "extract_metadata": "extract_metadata",
            "unsupported_project": "unsupported_project",
        },
    )

    workflow.add_edge("invalid_input", END)
    workflow.add_edge("clone_failed", END)
    workflow.add_edge("inspection_failed", END)
    workflow.add_edge("unsupported_project", END)

    # Section 2: Metadata and Source Resolution

    workflow.add_conditional_edges(
        "extract_metadata",
        route_after_metadata_extraction,
        {
            "check_metadata": "check_metadata",
            "metadata_extraction_failed": "metadata_extraction_failed",
        },
    )

    workflow.add_conditional_edges(
        "check_metadata",
        route_after_metadata_check,
        {
            "check_existing_spack_package": "check_existing_spack_package",
            "missing_metadata": "missing_metadata",
        },
    )

    workflow.add_conditional_edges(
        "check_existing_spack_package",
        route_after_spack_package_check,
        {
            "benchmark": "check_pypi_applicability",
            "new_package": "check_pypi_applicability",
        },
    )

    workflow.add_conditional_edges(
        "check_pypi_applicability",
        route_after_pypi_applicability,
        {
            "resolve_pypi_source": "resolve_pypi_source",
            "resolve_repository_source": "resolve_repository_source",
        },
    )

    workflow.add_conditional_edges(
        "resolve_pypi_source",
        route_after_pypi_resolution,
        {
            "derive_recipe_model": "derive_recipe_model",
            "resolve_repository_source": "resolve_repository_source",
            "pypi_resolution_failed": "pypi_resolution_failed",
        },
    )

    workflow.add_conditional_edges(
        "resolve_repository_source",
        route_after_repository_resolution,
        {
            "derive_recipe_model": "derive_recipe_model",
            "repository_source_unresolved": "repository_source_unresolved",
            "repository_resolution_failed": "repository_resolution_failed",
        },
    )

    workflow.add_edge("metadata_extraction_failed", END)
    workflow.add_edge("pypi_resolution_failed", END)
    workflow.add_edge("repository_source_unresolved", END)
    workflow.add_edge("repository_resolution_failed", END)

    workflow.add_conditional_edges(
        "derive_recipe_model",
        route_after_recipe_model,
        {
            "check_recipe_inputs": "check_recipe_inputs",
            "recipe_model_ambiguous": "recipe_model_ambiguous",
            "recipe_model_failed": "recipe_model_failed",
        },
    )

    workflow.add_conditional_edges(
        "check_recipe_inputs",
        route_after_recipe_inputs,
        {
            "generate_recipe": "generate_recipe",
            "recipe_inputs_missing": "recipe_inputs_missing",
        },
    )

    workflow.add_edge("recipe_model_ambiguous", END)
    workflow.add_edge("recipe_model_failed", END)
    workflow.add_edge("recipe_inputs_missing", END)

    workflow.add_edge("generate_recipe", END)
    workflow.add_edge("missing_metadata", END)

    return workflow.compile()


graph = build_graph()
