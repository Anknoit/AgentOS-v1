import json
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings


# class LLMClient:
#     def __init__(self):
#         self.client = OpenAI(api_key=settings.OPENAI_API_KEY)


#     # Use when billing is activated
#     @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
#     def reason(self, prompt: str) -> str:
#         response = self.client.responses.create(
#             model=settings.LLM_MODEL,
#             input=[
#                 {
#                     "role": "system",
#                     "content": (
#                         "You are an enterprise decision engine.\n"
#                         "You MUST return ONLY valid JSON.\n"
#                         "No markdown. No explanation. No text outside JSON."
#                     )
#                 },
#                 {
#                     "role": "user",
#                     "content": prompt
#                 }
#             ],
#             temperature=0.2
#         )

#         # ✅ Safely extract text (SDK-compatible)
#         output_text = response.output_text

#         if not output_text:
#             raise RuntimeError("LLM returned empty output")

#         # ✅ Hard validation
#         json.loads(output_text)

#         return output_text
    
class LLMClient:
    def reason(self, prompt: str) -> str:
        return """
        {
          "action": {
            "action_id": "RECOMMEND_ACTION",
            "action_type": "Recommend",
            "description": "Recommend next step to responsible human",
            "requires_human": true,
            "estimated_cost": 50,
            "expected_impact": 0.4
          },
          "confidence": 0.8,
          "reasoning": [
            "Deal has been idle beyond threshold",
            "Human follow-up required"
          ]
        }
        """