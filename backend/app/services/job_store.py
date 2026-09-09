"""Shared in-process job-status store.

Extracted from app.api.generate so both /api/generate and /api/blueprint can
poll the same job-status endpoint without a circular import between the two
routers. In-memory and single-process only — same limitation as the
_projects cache in app.api.projects; not durable across restarts or multiple
uvicorn workers.
"""
from typing import Dict

JOBS: Dict[str, dict] = {}
