import streamlit as st
from sqlalchemy.orm import Session

from app.persistence.db import SessionLocal
from app.persistence.models import DecisionModel


st.set_page_config(
    page_title="AgentOS – Decisions Dashboard",
    layout="wide"
)

st.title("🧠 AgentOS – Decisions Timeline")
st.caption("Audit trail of agentic decisions")


def get_decisions(db: Session):
    return (
        db.query(DecisionModel)
        .order_by(DecisionModel.created_at.desc())
        .limit(50)
        .all()
    )


db = SessionLocal()
decisions = get_decisions(db)
db.close()


if not decisions:
    st.warning("No decisions recorded yet.")
else:
    for d in decisions:
        with st.container(border=True):
            cols = st.columns(4)

            cols[0].markdown(f"**Entity ID**  \n{d.entity_id}")
            cols[1].markdown(f"**Action**  \n{d.action_id}")
            cols[2].markdown(f"**Confidence**  \n{round(d.confidence, 2)}")
            cols[3].markdown(f"**Risk**  \n{d.risk_level}")

            with st.expander("Reasoning"):
                for r in d.reasoning:
                    st.markdown(f"- {r}")

            st.caption(f"Decision ID: {d.decision_id}")
            st.caption(f"Created at: {d.created_at}")
