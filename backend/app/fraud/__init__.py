"""Fraud & abuse controls (Phase 6, build task 3): per-tenant velocity limits, anomaly-driven
holds, and prepaid-abuse protection. A tripped limit or a promoted anomaly places a hold that
gates further billable work until an operator releases it (ADR-0012).
"""
