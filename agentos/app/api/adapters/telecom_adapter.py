from app.core.ontology.entity import Entity
from app.core.ontology.signal import Signal
from app.core.ontology.entity import State
from app.core.ontology.entity import EntityType


def adapt_telecom_request(req):
    """
    Adapts telecom incident payload into core ontology objects.
    """

    entity = Entity(
        entity_id=req.entity_id,
        entity_type=EntityType.INCIDENT,   
        owner="NOC",                       
        priority="P2",                     
        lifecycle_stage="Active",          
        state=State(                       
            name=req.state,
            health_score=0.4 if req.state in ["Degrading", "Unstable"] else 0.9
        ),
        metadata={
            "industry": "telecom",
            "vip_users": req.vip_users,
            "blast_radius": req.blast_radius,
            "sop_key": req.sop_key,
        },
    )

    signals = [
        Signal(
            name=s.name,
            value=s.severity,
            source="telecom_simulator",
        )
        for s in req.signals
    ]

    return entity, signals, req.constraints
