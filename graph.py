import logging
from functools import wraps
from time import perf_counter
from spack_cli import remove_validation_container
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

from nodes.recipe_generation import (
    generate_recipe,
    route_after_recipe_generation,
)

from nodes.recipe_validation import (
    check_recipe_quality,
    recipe_quality_low,
    prepare_validation,
    route_after_validation_preparation,
    recipe_valid,
    recipe_validation_failed,
    route_after_recipe_quality,
    route_after_recipe_validation,
    validate_recipe,
    concretize_recipe,
    install_recipe,
    cleanup_validation,
    route_after_concretization,
    route_after_validation_cleanup,
)

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
from state import AgentState

logger = logging.getLogger(__name__)


def add_logged_node(builder, node_name, node_function) -> None:
    """Register a node with progress logging and execution history."""

    @wraps(node_function)
    def logged_node(state: AgentState) -> dict:
        package = state.get("package_name") or state.get("repo_url") or "unknown"
        depth = len(state.get("dependency_path") or [])
        history = list(state.get("node_history") or [])
        started = perf_counter()

        logger.info(
            "START node=%s package=%s depth=%s",
            node_name, package, depth,
        )

        try:
            update = node_function(state)
            update = {
                **update,
                "node_history": history + [node_name],
            }
        except BaseException:
            container_name = (state.get("validation") or {}).get("container_name")
            if container_name:
                try:
                    remove_validation_container(container_name)
                except OSError:
                    logger.exception(
                        "Could not remove validation container %s", container_name
                    )
            raise

        status = update.get("status", state.get("status", "unknown"))
        needs_human = update.get(
            "needs_human", state.get("needs_human", False)
        )
        log = logger.warning if needs_human else logger.info

        log(
            "END node=%s package=%s depth=%s elapsed=%.2fs status=%s",
            node_name,
            update.get("package_name") or package,
            depth,
            perf_counter() - started,
            status,
        )

        return update

    builder.add_node(node_name, logged_node)


def build_graph():
    """Build the workflow while keeping extraction, routing, and rendering separate."""
    workflow = StateGraph(AgentState)

    # Section 1: Repository and Project Detection
    add_logged_node(workflow, "validate_url", validate_url)
    add_logged_node(workflow, "initialize_state", initialize_state)
    add_logged_node(workflow, "clone_repo", clone_repo)
    add_logged_node(workflow, "inspect_files", inspect_files)
    add_logged_node(workflow, "detect_project_type", detect_project_type)

    add_logged_node(workflow, "invalid_input", invalid_input)
    add_logged_node(workflow, "clone_failed", clone_failed)
    add_logged_node(workflow, "inspection_failed", inspection_failed)
    add_logged_node(workflow, "unsupported_project", unsupported_project)

    # Section 2
    add_logged_node(workflow, "extract_metadata", extract_metadata)
    add_logged_node(workflow, "metadata_extraction_failed", metadata_extraction_failed)
    add_logged_node(workflow, "check_metadata", check_metadata)
    add_logged_node(workflow, "missing_metadata", missing_metadata)

    add_logged_node(workflow,
        "check_existing_spack_package",
        check_existing_spack_package,
    )
    add_logged_node(workflow,
        "spack_package_check_failed",
        spack_package_check_failed,
    )
    add_logged_node(workflow,
        "check_pypi_applicability",
        check_pypi_applicability,
    )
    add_logged_node(workflow, "resolve_pypi_source", resolve_pypi_source)
    add_logged_node(workflow, "pypi_resolution_failed", pypi_resolution_failed)

    add_logged_node(workflow, "resolve_repository_source", resolve_repository_source)
    add_logged_node(workflow,
        "repository_source_unresolved",
        repository_source_unresolved,
    )

    add_logged_node(workflow,
        "repository_resolution_failed",
        repository_resolution_failed,
    )

    add_logged_node(workflow, "derive_recipe_model", derive_recipe_model)
    add_logged_node(workflow, "recipe_model_ambiguous", recipe_model_ambiguous)
    add_logged_node(workflow, "recipe_model_failed", recipe_model_failed)
    add_logged_node(workflow, "check_missing_dependencies", check_missing_dependencies)
    add_logged_node(workflow, "resolve_dependency_source", resolve_dependency_source)
    add_logged_node(workflow, "check_recursion_guard", check_recursion_guard)
    add_logged_node(workflow,
        "package_dependency_recursively",
        package_dependency_recursively,
    )

    add_logged_node(workflow,
        "dependency_source_unresolved",
        dependency_source_unresolved,
    )
    add_logged_node(workflow,
        "recursive_dependency_failed",
        recursive_dependency_failed,
    )
    add_logged_node(workflow, "recursion_depth_reached", recursion_depth_reached)
    add_logged_node(workflow, "dependency_cycle_detected", dependency_cycle_detected)
    add_logged_node(workflow, "check_recipe_inputs", check_recipe_inputs)
    add_logged_node(workflow, "ready_for_recipe", ready_for_recipe)
    add_logged_node(workflow, "recipe_inputs_missing", recipe_inputs_missing)

    # Section 3
    add_logged_node(workflow, "generate_recipe", generate_recipe)
    add_logged_node(workflow, "prepare_validation", prepare_validation)
    add_logged_node(workflow, "validate_recipe", validate_recipe)
    add_logged_node(workflow, "concretize_recipe", concretize_recipe)
    add_logged_node(workflow, "install_recipe", install_recipe)
    add_logged_node(workflow, "cleanup_validation", cleanup_validation)
    add_logged_node(workflow, "recipe_validation_failed", recipe_validation_failed)
    add_logged_node(workflow, "check_recipe_quality", check_recipe_quality)
    add_logged_node(workflow, "recipe_valid", recipe_valid)
    add_logged_node(workflow, "recipe_quality_low", recipe_quality_low)

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
    workflow.add_conditional_edges(
        "generate_recipe",
        route_after_recipe_generation,
        {
            "prepare_validation": "prepare_validation",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "prepare_validation",
        route_after_validation_preparation,
        {
            "validate_recipe": "validate_recipe",
            "cleanup_validation": "cleanup_validation",
        },
    )

    workflow.add_conditional_edges(
        "validate_recipe",
        route_after_recipe_validation,
        {
            "concretize_recipe": "concretize_recipe",
            "cleanup_validation": "cleanup_validation",
        },
    )

    workflow.add_conditional_edges(
        "concretize_recipe",
        route_after_concretization,
        {
            "install_recipe": "install_recipe",
            "cleanup_validation": "cleanup_validation",
        },
    )

    workflow.add_edge("install_recipe", "cleanup_validation")

    workflow.add_conditional_edges(
        "cleanup_validation",
        route_after_validation_cleanup,
        {
            "check_recipe_quality": "check_recipe_quality",
            "recipe_validation_failed": "recipe_validation_failed",
        },
    )

    workflow.add_edge("recipe_validation_failed", END)
    workflow.add_conditional_edges(
        "check_recipe_quality",
        route_after_recipe_quality,
        {
            "recipe_valid": "recipe_valid",
            "recipe_quality_low": "recipe_quality_low",
        },
    )

    workflow.add_edge("recipe_valid", END)
    workflow.add_edge("recipe_quality_low", END)
    workflow.add_edge("missing_metadata", END)

    return workflow.compile()


graph = build_graph()
