from app.industries.telecom.decision_override import telecom_execution_decision

base_decision = {
    "state": "Degrading",
    "confidence": 0.78,
}

action, reason = telecom_execution_decision(
    base_decision=base_decision,
    sop_key="CLEAR_STALE_SESSIONS",
    has_vip_users=True,
)

print("ACTION:", action)
print("REASON:", reason)
