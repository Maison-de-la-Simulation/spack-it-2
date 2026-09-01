from langgraph.graph import END, START, StateGraph

from legacy_nodes import (
    derive_recipe_model,
    extract_metadata,
    generate_recipe,
    resolve_pypi_source,
    route_after_metadata,
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


def ready_for_recipe(state: AgentState) -> dict:
    """Mark the state as having enough evidence to start recipe generation."""
    return {
        "current_stage": "ready_for_recipe",
        "status": "ready for recipe generation",
        "score": 2,
    }


def unsupported(state: AgentState) -> dict:
    """Stop when the project is outside the prototype's supported scope."""
    return {
        "current_stage": "unsupported",
        "status": "unsupported project type",
        "needs_human": True,
    }


def missing_metadata(state: AgentState) -> dict:
    """Stop when recipe generation would require guessing required metadata."""
    return {
        "current_stage": "missing_metadata",
        "status": "missing or unclear metadata",
        "needs_human": True,
    }


def human_review(state: AgentState) -> dict:
    """Stop when the workflow has detected an ambiguity it cannot resolve safely."""
    return {
        "current_stage": "human_review",
        "status": "human review required",
        "needs_human": True,
    }


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
    workflow.add_node("resolve_pypi_source", resolve_pypi_source)
    workflow.add_node("derive_recipe_model", derive_recipe_model)

    # Section 3
    workflow.add_node("ready_for_recipe", ready_for_recipe)
    workflow.add_node("generate_recipe", generate_recipe)

    # Existing exit nodes
    workflow.add_node("unsupported", unsupported)
    workflow.add_node("missing_metadata", missing_metadata)
    workflow.add_node("human_review", human_review)

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

    workflow.add_edge("extract_metadata", "resolve_pypi_source")

    # Routing happens only after source resolution because a recipe without a
    # resolved source checksum should not reach generation.
    workflow.add_conditional_edges(
        "resolve_pypi_source",
        route_after_metadata,
        {
            "derive_recipe_model": "derive_recipe_model",
            "unsupported": "unsupported",
            "missing_metadata": "missing_metadata",
            "human_review": "human_review",
        },
    )

    workflow.add_conditional_edges(
        "derive_recipe_model",
        route_after_recipe_model,
        {
            "ready_for_recipe": "ready_for_recipe",
            "human_review": "human_review",
        },
    )

    workflow.add_edge("ready_for_recipe", "generate_recipe")
    workflow.add_edge("generate_recipe", END)
    workflow.add_edge("unsupported", END)
    workflow.add_edge("missing_metadata", END)
    workflow.add_edge("human_review", END)

    return workflow.compile()


graph = build_graph()