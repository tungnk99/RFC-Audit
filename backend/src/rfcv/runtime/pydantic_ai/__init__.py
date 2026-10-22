"""Runtime agent dựa trên PydanticAI (thực thi bằng `pydantic-ai-slim`, skills bằng `pydantic-ai-harness`)."""

from __future__ import annotations

from rfcv.runtime.pydantic_ai.models import anthropic_factory, openai_compatible_factory
from rfcv.runtime.pydantic_ai.runner import PydanticAIRoleRunner, loaded_skills
from rfcv.runtime.pydantic_ai.skills import SkillLibraryWorkspace, skills_capability

create_runner = PydanticAIRoleRunner  # nhà máy đăng ký ở nhóm `rfcv.agent_runtimes`

__all__ = [
    "PydanticAIRoleRunner",
    "SkillLibraryWorkspace",
    "anthropic_factory",
    "create_runner",
    "loaded_skills",
    "openai_compatible_factory",
    "skills_capability",
]
