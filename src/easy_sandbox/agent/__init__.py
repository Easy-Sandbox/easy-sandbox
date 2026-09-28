# Built-in agent CLI wrappers
from easy_sandbox.agent.builtin import (
    BUILTIN_AGENTS,
    AgentModule,
    match_builtin_agent,
)
from easy_sandbox.agent.infer import (
    TEMPLATE_CATALOG,
    InferResult,
    TemplateProfile,
    infer_template,
)

__all__ = [
    "AgentModule",
    "BUILTIN_AGENTS",
    "match_builtin_agent",
    "InferResult",
    "TEMPLATE_CATALOG",
    "TemplateProfile",
    "infer_template",
]
