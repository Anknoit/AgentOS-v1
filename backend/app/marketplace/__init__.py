"""Marketplace (Phase 6, build task 4): publish and install agent templates and connector configs
across tenants — the network-effect lever. Listings are a public catalogue (outside RLS); secrets
are never published, so installing copies config into the caller's tenant and the installer brings
their own credentials (ADR-0012).
"""
