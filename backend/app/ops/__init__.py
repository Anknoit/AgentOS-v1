"""Operational tooling (Phase 5): backup/restore, stream replay, scale health.

These are the HA/DR and reliability tools that sit beside the request path — invoked by the
``agentos`` CLI and a thin tenant-scoped ``/v1/ops`` API. See docs/runbook-dr.md for RPO/RTO.
"""
