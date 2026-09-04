from typing import TypedDict


class AgentState(TypedDict):
    """Shared data passed between LangGraph nodes.

    ``metadata`` keeps evidence extracted from upstream sources.
    ``recipe_model`` holds the normalized Spack decisions derived from that
    evidence, so rendering does not need to repeat or hide those decisions.
    """

    repo_url: str
    repo_path: str | None
    package_name: str | None
    languages: list[str]
    build_system: str | None
    mode: str | None
    metadata: dict
    recipe_model: dict | None
    current_stage: str
    errors: list[str]
    score: int
    attempts: int
    needs_human: bool
    status: str