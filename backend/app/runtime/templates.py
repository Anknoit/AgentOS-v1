"""Starter agent templates.

A template is a factory for an immutable ``AgentVersionConfig`` — the config that an agent is
created from and that a run pins. Phase 1 ships **Support Desk** end to end; the other roles
(Receptionist, Social Media, HR) are registered as stubs and fleshed out as their connectors
land in later phases. Keeping these as data (not code paths) is the "config is data, versioned"
principle: deploying from a template just writes an ``agent_version``.
"""

from __future__ import annotations

from app.schemas.agent import AgentVersionConfig

SUPPORT_DESK = "support_desk"


def support_desk_config(model: str = "gpt-4o-mini") -> AgentVersionConfig:
    return AgentVersionConfig(
        model=model,
        system_prompt=(
            "You are a Support Desk agent. Answer the customer's question clearly and politely, "
            "grounding your answer in the knowledge base results provided. If you are unsure, say "
            "so and offer to escalate to a human."
        ),
        tools=["kb_search"],
        guardrails={"max_steps": 8, "max_output_tokens": 1024},
        knowledge=["support-kb"],
        connector_bindings={},
    )


_TEMPLATES = {
    SUPPORT_DESK: support_desk_config,
}


def template_config(name: str, *, model: str = "gpt-4o-mini") -> AgentVersionConfig | None:
    factory = _TEMPLATES.get(name)
    return factory(model=model) if factory else None


def available_templates() -> list[str]:
    return sorted(_TEMPLATES)
