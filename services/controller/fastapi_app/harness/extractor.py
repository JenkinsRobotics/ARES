"""ARES Harness Feature Matrix Extractor.

Decomposes donor source code and complex task descriptions into
discrete, machine-verifiable FeatureRequirement items.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from .schemas import FeatureRequirement, VerificationMatrix


class FeatureExtractor:
    """Extracts granular mechanical requirements into an immutable contract matrix."""

    @classmethod
    def create_from_items(
        cls,
        task_description: str,
        items_data: List[dict],
    ) -> VerificationMatrix:
        """Create a VerificationMatrix from a list of structured item dictionaries."""
        reqs = []
        for idx, d in enumerate(items_data, start=1):
            reqs.append(
                FeatureRequirement(
                    id=d.get("id", f"req-{idx}"),
                    title=d.get("title", f"Requirement {idx}"),
                    description=d.get("description", ""),
                    donor_reference=d.get("donor_reference"),
                    target_files=d.get("target_files", []),
                    state_machine_steps=d.get("state_machine_steps", []),
                    status="pending",
                )
            )
        return VerificationMatrix(
            matrix_id=f"matrix-{uuid.uuid4().hex[:8]}",
            task_description=task_description,
            items=reqs,
        )

    @classmethod
    def decompose_chat_parity_task(cls) -> VerificationMatrix:
        """Standard extraction matrix for Legacy WebUI parity parity."""
        items = [
            {
                "id": "model-group-accordion",
                "title": "Collapsible Provider Accordions",
                "description": "Provider groups render with chevrons and counts. Only active provider open by default; clicking header toggles open/closed.",
                "donor_reference": "ui.js:4480-4515",
                "target_files": ["apps/web/src/features/chat/ConversationPage.tsx", "apps/web/src/features/chat/composer/chips.css"],
                "state_machine_steps": ["active_provider_open_default", "header_click_toggles_group", "chevron_rotates"],
            },
            {
                "id": "model-search-state-machine",
                "title": "Search Expand/Collapse State Machine",
                "description": "Typing in search auto-expands all matching provider groups; clearing search restores unselected groups to collapsed.",
                "donor_reference": "ui.js:4360-4375",
                "target_files": ["apps/web/src/features/chat/ConversationPage.tsx"],
                "state_machine_steps": ["query_typed_expands_all", "query_cleared_resets_collapse"],
            },
            {
                "id": "model-custom-input",
                "title": "Custom Model Direct Input",
                "description": "Dedicated input bar with + action button allowing arbitrary model IDs (e.g. openai/gpt-5.4).",
                "donor_reference": "ui.js:4201-4206",
                "target_files": ["apps/web/src/features/chat/ConversationPage.tsx"],
                "state_machine_steps": ["input_value_typed", "plus_clicked_or_enter_pressed_sets_model"],
            },
            {
                "id": "model-two-line-layout",
                "title": "Two-Line Model Option Layout",
                "description": "Display friendly name + badges (DEFAULT/SELECTED) on row 1; raw monospace ID on row 2.",
                "donor_reference": "ui.js:4345-4355",
                "target_files": ["apps/web/src/features/chat/ConversationPage.tsx"],
                "state_machine_steps": ["friendly_name_rendered", "monospace_id_rendered"],
            },
            {
                "id": "turn-branch-fork-api",
                "title": "Session Branch & Fork Action",
                "description": "Wire onBranch handler to active ARES session forking endpoint rather than console.log stub.",
                "donor_reference": "messages.js:150-250",
                "target_files": ["apps/web/src/features/chat/ConversationPage.tsx"],
                "state_machine_steps": ["click_branch_creates_session", "switches_to_forked_session"],
            },
        ]
        return cls.create_from_items("Legacy WebUI Chat Parity", items)
