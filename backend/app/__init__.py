"""AgentOS backend — FastAPI control plane.

One codebase, two deployment modes: a local sidecar that Electron spawns, and the cloud
multi-tenant service. The client points at a configurable backend URL and never assumes which.
"""

__version__ = "0.0.0"
