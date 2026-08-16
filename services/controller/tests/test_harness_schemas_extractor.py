import pytest
from fastapi_app.harness.schemas import FeatureRequirement, VerificationMatrix
from fastapi_app.harness.extractor import FeatureExtractor

def test_feature_requirement_schema():
    req = FeatureRequirement(
        id="accordion-toggle",
        title="Accordion Toggle",
        description="Clicking header toggles body",
        donor_reference="ui.js:4480",
        target_files=["src/Component.tsx"],
        state_machine_steps=["open", "closed"],
    )
    assert req.status == "pending"
    assert req.attempts_count == 0
    assert req.donor_reference == "ui.js:4480"

def test_verification_matrix_progress_tracking():
    items = [
        {"id": "item-1", "title": "Item 1", "description": "First"},
        {"id": "item-2", "title": "Item 2", "description": "Second"},
    ]
    matrix = FeatureExtractor.create_from_items("Sample Task", items)
    assert matrix.total_items == 2
    assert matrix.verified_items == 0
    assert matrix.is_complete is False

    matrix.items[0].status = "verified"
    assert matrix.verified_items == 1
    assert matrix.is_complete is False

    matrix.items[1].status = "verified"
    assert matrix.verified_items == 2
    assert matrix.is_complete is True

def test_decompose_chat_parity_task():
    matrix = FeatureExtractor.decompose_chat_parity_task()
    assert matrix.total_items >= 5
    ids = [item.id for item in matrix.items]
    assert "model-group-accordion" in ids
    assert "model-search-state-machine" in ids
    assert "model-custom-input" in ids
    assert "turn-branch-fork-api" in ids
