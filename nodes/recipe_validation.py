from state import AgentState


def validate_recipe(state: AgentState) -> dict:
    """Return True until the validation checks are implemented."""
    return {
        "current_stage": "validate_recipe",
        "validation_result": True,
        "status": "recipe validation passed",
    }


def route_after_recipe_validation(state: AgentState) -> str:
    """Route after recipe validation."""
    if state["validation_result"]:
        return "check_recipe_quality"

    return "recipe_validation_failed"


def recipe_validation_failed(state: AgentState) -> dict:
    """Stop when recipe validation fails."""
    return {
        "current_stage": "recipe_validation_failed",
        "status": "recipe validation failed",
        "needs_human": True,
    }


def check_recipe_quality(state: AgentState) -> dict:
    """Return a fixed quality score until scoring is implemented."""
    return {
        "current_stage": "check_recipe_quality",
        "quality_score": 90.0,
        "status": "recipe quality checked",
    }


def route_after_recipe_quality(state: AgentState) -> str:
    """Route after the recipe quality check."""
    quality_score = state["quality_score"]

    if quality_score is not None and quality_score >= 90:
        return "recipe_valid"

    return "recipe_quality_low"


def recipe_valid(state: AgentState) -> dict:
    """Mark the recipe as valid."""
    return {
        "current_stage": "recipe_valid",
        "status": "recipe valid",
        "needs_human": False,
    }


def recipe_quality_low(state: AgentState) -> dict:
    """Stop when the quality score needs review."""
    return {
        "current_stage": "recipe_quality_low",
        "status": "recipe quality needs review",
        "needs_human": True,
    }
