# This keeps your core ontology unchanged.

def extract_telecom_context(entity: dict) -> dict:
    """
    Extract telecom-specific flags from entity metadata.
    """

    return {
        "has_vip_users": entity.get("vip_users", False),
        "blast_radius": entity.get("blast_radius", "LOW"),
        "state": entity.get("state"),
    }
