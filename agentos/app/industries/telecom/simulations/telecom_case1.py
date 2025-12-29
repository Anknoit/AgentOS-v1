from app.industries.telecom.decision_override import telecom_execution_decision

base_decision = {
    "state": "Unstable",
    "confidence": 0.82,
}

action, reason = telecom_execution_decision(
    base_decision=base_decision,
    sop_key="RADIO_SOFT_RESET",
    has_vip_users=False,
)

print("ACTION:", action)
print("REASON:", reason)
