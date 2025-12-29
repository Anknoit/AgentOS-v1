from app.industries.telecom.policy import can_execute_sop
from app.industries.telecom.sop_registry import TELECOM_SOPS


def telecom_override(
    base_action: str,
    confidence: float,
    telecom_context: dict,
    sop_key: str | None = None,
):
    """
    Overrides EXECUTE decisions if telecom policy blocks it.
    """

    if base_action != "EXECUTE":
        return base_action, "Non-executable action"

    if not sop_key or sop_key not in TELECOM_SOPS:
        return "RECOMMEND", "SOP not whitelisted"

    allowed, reason = can_execute_sop(
        state=telecom_context["state"],
        confidence=confidence,
        blast_radius=telecom_context["blast_radius"],
        has_vip_users=telecom_context["has_vip_users"],
    )

    if not allowed:
        return "RECOMMEND", reason

    return "EXECUTE", TELECOM_SOPS[sop_key]["description"]
