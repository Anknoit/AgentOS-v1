"""WebSocket run-event streaming.

Phase 0 streams directly from ``app/api/v1/runs.py``; a dedicated pub/sub fan-out
(worker -> client) lands in Phase 1.
"""
