from langgraph.graph import END, START, StateGraph

from nodes.metadata_resolution import (
    check_existing_spack_package,
    spack_package_check_failed,
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

from nodes.dependency_resolution import (
    check_missing_dependencies,
    check_recursion_guard,
    dependency_cycle_detected,
    dependency_source_unresolved,
    package_dependency_recursively,
    recursive_dependency_failed,
    recursion_depth_reached,
    resolve_dependency_source,
    route_after_dependency_check,
    route_after_dependency_source,
    route_after_recursive_dependency,
    route_after_recursion_guard,
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
    ready_for_recipe,
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
from nodes.validation import (
    route_after_recipe_generation,
    route_after_validation,
    validate_recipe,
    validation_failed,
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
        "spack_package_check_failed",
        spack_package_check_failed,
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
    workflow.add_node("check_missing_dependencies", check_missing_dependencies)
    workflow.add_node("resolve_dependency_source", resolve_dependency_source)
    workflow.add_node("check_recursion_guard", check_recursion_guard)
    workflow.add_node(
        "package_dependency_recursively",
        package_dependency_recursively,
    )

    workflow.add_node(
        "dependency_source_unresolved",
        dependency_source_unresolved,
    )
    workflow.add_node(
        "recursive_dependency_failed",
        recursive_dependency_failed,
    )
    workflow.add_node("recursion_depth_reached", recursion_depth_reached)
    workflow.add_node("dependency_cycle_detected", dependency_cycle_detected)
    workflow.add_node("check_recipe_inputs", check_recipe_inputs)
    workflow.add_node("ready_for_recipe", ready_for_recipe)
    workflow.add_node("recipe_inputs_missing", recipe_inputs_missing)

    # Section 3
    workflow.add_node("generate_recipe", generate_recipe)

    # Section 4: Recipe Validation
    workflow.add_node("validate_recipe", validate_recipe)
    workflow.add_node("validation_failed", validation_failed)

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
            "spack_package_check_failed": "spack_package_check_failed",
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
    workflow.add_edge("spack_package_check_failed", END)
    workflow.add_edge("pypi_resolution_failed", END)
    workflow.add_edge("repository_source_unresolved", END)
    workflow.add_edge("repository_resolution_failed", END)

    workflow.add_conditional_edges(
        "derive_recipe_model",
        route_after_recipe_model,
        {
            "check_missing_dependencies": "check_missing_dependencies",
            "recipe_model_ambiguous": "recipe_model_ambiguous",
            "recipe_model_failed": "recipe_model_failed",
        },
    )

    workflow.add_conditional_edges(
        "check_missing_dependencies",
        route_after_dependency_check,
        {
            "resolve_dependency_source": "resolve_dependency_source",
            "check_recipe_inputs": "check_recipe_inputs",
        },
    )

    workflow.add_conditional_edges(
        "resolve_dependency_source",
        route_after_dependency_source,
        {
            "check_recursion_guard": "check_recursion_guard",
            "dependency_source_unresolved": "dependency_source_unresolved",
        },
    )

    workflow.add_conditional_edges(
        "check_recursion_guard",
        route_after_recursion_guard,
        {
            "package_dependency_recursively": "package_dependency_recursively",
            "recursion_depth_reached": "recursion_depth_reached",
            "dependency_cycle_detected": "dependency_cycle_detected",
        },
    )

    workflow.add_conditional_edges(
        "package_dependency_recursively",
        route_after_recursive_dependency,
        {
            "check_missing_dependencies": "check_missing_dependencies",
            "recursive_dependency_failed": "recursive_dependency_failed",
        },
    )

    workflow.add_conditional_edges(
        "check_recipe_inputs",
        route_after_recipe_inputs,
        {
            "ready_for_recipe": "ready_for_recipe",
            "recipe_inputs_missing": "recipe_inputs_missing",
        },
    )

    workflow.add_edge("recipe_model_ambiguous", END)
    workflow.add_edge("recipe_model_failed", END)
    workflow.add_edge("recipe_inputs_missing", END)

    workflow.add_edge("dependency_source_unresolved", END)
    workflow.add_edge("recursive_dependency_failed", END)
    workflow.add_edge("recursion_depth_reached", END)
    workflow.add_edge("dependency_cycle_detected", END)

    workflow.add_edge("ready_for_recipe", "generate_recipe")

    # Section 4: Recipe Validation. Only the top-level run validates; child
    # runs of the recursive dependency workflow end at recipe generation.
    workflow.add_conditional_edges(
        "generate_recipe",
        route_after_recipe_generation,
        {
            "validate_recipe": "validate_recipe",
            "done": END,
        },
    )

    workflow.add_conditional_edges(
        "validate_recipe",
        route_after_validation,
        {
            "validated": END,
            "validation_failed": "validation_failed",
        },
    )

    workflow.add_edge("validation_failed", END)
    workflow.add_edge("missing_metadata", END)

    return workflow.compile()


graph = build_graph()
