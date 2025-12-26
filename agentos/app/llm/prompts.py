def nba_prompt(entity, signals, actions, urgency) -> str:
    return f"""
You are an enterprise decision engine.

You are NOT allowed to invent actions.
You MUST choose one action from the list below.

ENTITY:
{entity.model_dump()}

SIGNALS:
{[s.model_dump() for s in signals]}

URGENCY SCORE:
{urgency}

ALLOWED ACTIONS:
{[a.model_dump() for a in actions]}

Return STRICT JSON in this exact schema:

{{
  "action": {{
    "action_id": "<must match allowed action_id>",
    "action_type": "<must match>",
    "description": "<must match>",
    "requires_human": true/false,
    "estimated_cost": number,
    "expected_impact": number
  }},
  "confidence": number between 0 and 1,
  "reasoning": ["bullet 1", "bullet 2"]
}}

No extra text. No markdown. No explanation outside JSON.
"""
