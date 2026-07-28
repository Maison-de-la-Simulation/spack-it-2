from typing import TypedDict


class AgentState(TypedDict):
    repo_url: str
    repo_path: str | None
    package_name: str | None
    languages: list[str]
    build_system: str | None
    metadata: dict
    current_stage: str
    errors: list[str]
    score: int
    attempts: int
    needs_human: bool
    status: str