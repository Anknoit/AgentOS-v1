from app.llm.client import LLMClient

llm = LLMClient()

prompt = """
Return JSON:
{
  "action": {
    "action_id": "WAIT",
    "action_type": "Wait",
    "description": "Take no action",
    "requires_human": false,
    "estimated_cost": 0,
    "expected_impact": 0
  },
  "confidence": 0.9,
  "reasoning": ["Test successful"]
}
"""

print(llm.reason(prompt))
