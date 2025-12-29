import streamlit as st
from app.persistence.db import SessionLocal
from app.persistence.models import DecisionModel

st.set_page_config(page_title="Telecom NOC – AgentOS", layout="wide")
st.title("📡 Telecom NOC – AgentOS Decision Console")

db = SessionLocal()
decisions = (
    db.query(DecisionModel)
    .order_by(DecisionModel.created_at.desc())
    .limit(20)
    .all()
)
db.close()

for d in decisions:
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Entity", d.entity_id)
        col2.metric("Action", d.action_type)
        col3.metric("Confidence", round(d.confidence, 2))
        col4.metric("Risk", d.risk_level)

        with st.expander("Reasoning"):
            for r in d.reasoning:
                st.write("-", r)

        st.caption(f"Decision ID: {d.decision_id}")
