import requests
import time

API_URL = "http://localhost:8000/telecom/decide"

telecom_incidents = [
    {
        "entity_id": "eNodeB-4521",
        "industry": "telecom",
        "state": "Unstable",
        "vip_users": False,
        "blast_radius": "LOW",
        "sop_key": "RADIO_SOFT_RESET",
        "signals": [
            {"name": "heartbeat_loss", "severity": "minor"},
            {"name": "rrc_failures", "severity": "minor"},
        ],
        "constraints": []
    },
    {
        "entity_id": "AMF-01",
        "industry": "telecom",
        "state": "Degrading",
        "vip_users": True,
        "blast_radius": "HIGH",
        "sop_key": "CORE_RESTART",
        "signals": [
            {"name": "registration_failures", "severity": "major"},
        ],
        "constraints": ["no_core_restart"]
    }
]

for incident in telecom_incidents:
    print("\n🚨 Injecting Incident:", incident["entity_id"])
    response = requests.post(API_URL, json=incident)
    print("Agent Decision:", response.json())
    time.sleep(3)
