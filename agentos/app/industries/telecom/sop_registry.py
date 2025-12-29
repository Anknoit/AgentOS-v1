# Only sops listed here can be executed
TELECOM_SOPS = {
    "RADIO_SOFT_RESET": {
        "allowed_states": ["Unstable"],
        "description": "Soft reset of radio unit",
    },
    "CLEAR_STALE_SESSIONS": {
        "allowed_states": ["Degrading"],
        "description": "Clear stale AAA sessions",
    },
}
