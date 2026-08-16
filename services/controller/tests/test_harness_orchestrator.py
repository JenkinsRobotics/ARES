import pytest
from fastapi_app.harness.orchestrator import HarnessOrchestrator
from fastapi_app.harness.extractor import FeatureExtractor

@pytest.mark.asyncio
async def test_verify_diff_fast_reject():
    diff_with_stub = """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const handleBranch = (id) => console.log("stub", id);
"""
    res = await HarnessOrchestrator.verify_diff(
        task_description="Branch Action",
        diff_text=diff_with_stub,
    )
    assert res.passed is False
    assert res.remediation_prompt is not None
    assert "NO_CONSOLE_LOG_STUB" in res.remediation_prompt

@pytest.mark.asyncio
async def test_verify_diff_clean_pass():
    clean_diff = """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const handleBranch = (id) => api.forkSession(id);
"""
    res = await HarnessOrchestrator.verify_diff(
        task_description="Branch Action",
        diff_text=clean_diff,
    )
    assert res.passed is True
    assert res.remediation_prompt is None

@pytest.mark.asyncio
async def test_run_matrix_loop_autonomous_remediation():
    items = [
        {"id": "branch-action", "title": "Wire Branch Action", "description": "Must not stub"}
    ]
    matrix = FeatureExtractor.create_from_items("Session Branch Task", items)

    # Worker simulation: attempt 1 generates a stub, attempt 2 provides real code
    async def simulated_worker(item, remediation_prompt):
        if remediation_prompt is None:
            # First attempt: lazy model creates stub
            return """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const branch = () => console.log("stub");
"""
        else:
            # Second attempt: model receives remediation feedback and fixes it
            assert "Deterministic Verification Gate Failed" in remediation_prompt
            return """--- a/src/app.tsx
+++ b/src/app.tsx
@@ -1,2 +1,3 @@
+const branch = () => api.forkSession();
"""

    completed_matrix = await HarnessOrchestrator.run_matrix_loop(
        matrix=matrix,
        worker_turn_fn=simulated_worker,
        max_attempts=3,
    )

    assert completed_matrix.is_complete is True
    assert completed_matrix.overall_status == "verified"
    assert completed_matrix.items[0].status == "verified"
    assert completed_matrix.items[0].attempts_count == 2
