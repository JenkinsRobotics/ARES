"""Legacy hermes-webui setup docs were removed from the tree (2026-08-14).

Kept as a skip-marker so old CI job names do not fail hard.
"""

import pytest


def test_advanced_chat_docs_name_gateway_approval_runs_api_opt_in():
    pytest.skip("docs/advanced-chat-setup.md removed from ARES; see Desktop ARES-removed-2026-08-14")


def test_docker_docs_name_webui_service_runs_api_opt_in_for_approval_cards():
    pytest.skip("docs/docker.md removed from ARES; see Desktop ARES-removed-2026-08-14")
