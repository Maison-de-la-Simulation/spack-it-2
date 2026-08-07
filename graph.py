from langgraph.graph import END, START, StateGraph

from nodes import (
    clone_repo,
    detect_project_type,
    extract_metadata,
    inspect_files,
    resolve_pypi_source,
    route_after_metadata,
    generate_recipe,
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

    workflow.add_node("clone_repo", clone_repo)
    workflow.add_node("inspect_files", inspect_files)
    workflow.add_node("detect_project_type", detect_project_type)
    workflow.add_node("extract_metadata", extract_metadata)
    workflow.add_node("resolve_pypi_source", resolve_pypi_source)

    workflow.add_node("ready_for_recipe", ready_for_recipe)
    workflow.add_node("unsupported", unsupported)
    workflow.add_node("missing_metadata", missing_metadata)
    workflow.add_node("human_review", human_review)
    workflow.add_node("generate_recipe", generate_recipe)

    workflow.add_edge(START, "clone_repo")
    workflow.add_edge("clone_repo", "inspect_files")
    workflow.add_edge("inspect_files", "detect_project_type")
    workflow.add_edge("detect_project_type", "extract_metadata")
    workflow.add_edge("extract_metadata", "resolve_pypi_source")

    # Routing happens only after source resolution because a recipe without a
    # resolved source checksum should not reach generation.
    workflow.add_conditional_edges(
        "resolve_pypi_source",
        route_after_metadata,
        {
            "ready_for_recipe": "ready_for_recipe",
            "unsupported": "unsupported",
            "missing_metadata": "missing_metadata",
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