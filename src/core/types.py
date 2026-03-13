"""Type aliases used across the entire codebase."""
from __future__ import annotations

from typing import NewType

JobId = NewType("JobId", str)
ProposalId = NewType("ProposalId", str)
ClientId = NewType("ClientId", str)
ExperimentId = NewType("ExperimentId", str)
PlatformName = NewType("PlatformName", str)
