import json
from app.core.ontology.action import Action


def parse_llm_response(response: str) -> dict:
    parsed = json.loads(response)

    if "action" not in parsed:
        raise ValueError("Invalid LLM response")

    return {
        "action": Action(**parsed["action"]),
        "confidence": parsed.get("confidence", 0.5),
        "reasoning": parsed.get("reasoning", [])
    }
