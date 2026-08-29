from __future__ import annotations

from core.control_plane import AgentDefinition, DefinitionStore, SharingGrant, evaluate_grant


def test_cross_agent_access_is_denied_without_explicit_grant():
    definition = AgentDefinition(id="hermes", runtime="hermes")
    decision = evaluate_grant(
        definition, resource="tool", resource_id="jaeger.shell", mode="use"
    )
    assert decision.allowed is False
    assert decision.reason == "no_explicit_grant"


def test_credential_grant_returns_reference_not_secret():
    definition = AgentDefinition(
        id="jaeger",
        runtime="jaeger",
        grants=(SharingGrant(
            resource="credential",
            resource_id="github",
            grantee="jaeger",
            credential_reference="keychain://ares/github/jaeger",
            approval_required=True,
        ),),
    )
    decision = evaluate_grant(
        definition, resource="credential", resource_id="github", mode="use"
    )
    assert decision.allowed is True
    assert decision.approval_required is True
    assert decision.credential_reference == "keychain://ares/github/jaeger"


def test_definition_store_round_trip(tmp_path):
    store = DefinitionStore(tmp_path / "definitions.json")
    saved = store.put(AgentDefinition(id="hermes", runtime="hermes"))
    assert store.get("hermes") == saved
    assert (tmp_path / "definitions.json").stat().st_mode & 0o777 == 0o600
