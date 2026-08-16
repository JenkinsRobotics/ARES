"""Data schemas for ARES Multi-Agent Verification Harness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class FeatureRequirement(BaseModel):
    """A granular, machine-verifiable feature requirement."""
    id: str = Field(description="Unique ID for this requirement, e.g., 'model-group-accordion'")
    title: str = Field(description="Short human-readable title")
    description: str = Field(description="Exact mechanical behavior required")
    donor_reference: Optional[str] = Field(default=None, description="Donor file & line citation, e.g., 'ui.js:4480-4515'")
    target_files: List[str] = Field(default_factory=list, description="Target repo files where this must be implemented")
    state_machine_steps: List[str] = Field(default_factory=list, description="List of discrete states (e.g. ['active_open', 'search_expand', 'clear_reset'])")
    status: Literal["pending", "in_progress", "verified", "failed"] = "pending"
    attempts_count: int = 0
    failure_details: Optional[str] = None


class VerificationMatrix(BaseModel):
    """The immutable contract matrix for an engineering task."""
    matrix_id: str
    task_description: str
    items: List[FeatureRequirement]
    overall_status: Literal["pending", "in_progress", "verified", "failed"] = "pending"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def verified_items(self) -> int:
        return sum(1 for item in self.items if item.status == "verified")

    @property
    def is_complete(self) -> bool:
        return self.total_items > 0 and self.verified_items == self.total_items
