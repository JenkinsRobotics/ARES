"""``session.model_provider`` must reflect the model that actually answered.

Before this fix, ARES wrote the *requested* model/provider into the session
before contacting the runtime, and never corrected it afterward — so a turn
that silently fell back (e.g. picking an unresolvable local model, which
fell back to the cloud default) left the session claiming the local pick had
served the answer. `reconcile_session_provider_after_turn` closes that gap.
"""

from types import SimpleNamespace

from api.model_resolution import reconcile_session_provider_after_turn


def _session(*, model="qwen3.6:35b-mlx", provider="local"):
    return SimpleNamespace(model=model, model_provider=provider)


def test_fallback_reconciles_session_provider_and_model():
    session = _session()
    routing = {
        "used_model": "qwen3.5:397b",
        "used_provider": "ollama-cloud",
        "requested_model": "qwen3.6:35b-mlx",
        "requested_provider": "local",
        "provider_changed": True,
        "model_changed": True,
        "has_failover": True,
    }

    reconcile_session_provider_after_turn(
        session,
        routing,
        turn_owns_model=True,
        last_persisted_model="qwen3.6:35b-mlx",
        last_persisted_provider="local",
    )

    assert session.model_provider == "ollama-cloud"
    assert session.model == "qwen3.5:397b"


def test_no_fallback_leaves_session_untouched():
    """A routine matching turn must never trigger a rewrite."""
    session = _session(model="qwen3.5:397b", provider="ollama-cloud")
    routing = {
        "used_model": "qwen3.5:397b",
        "used_provider": "ollama-cloud",
        "provider_changed": False,
        "model_changed": False,
    }

    reconcile_session_provider_after_turn(
        session,
        routing,
        turn_owns_model=True,
        last_persisted_model="qwen3.5:397b",
        last_persisted_provider="ollama-cloud",
    )

    assert session.model_provider == "ollama-cloud"
    assert session.model == "qwen3.5:397b"


def test_ownership_guard_skips_when_turn_does_not_own_model():
    """A concurrent, newer picker write must never be clobbered by a stale turn."""
    session = _session(model="glm-5.1", provider="ollama-cloud")
    routing = {
        "used_model": "qwen3.5:397b",
        "used_provider": "ollama-cloud",
        "provider_changed": True,
        "model_changed": True,
    }

    reconcile_session_provider_after_turn(
        session,
        routing,
        turn_owns_model=False,
        last_persisted_model="qwen3.6:35b-mlx",
        last_persisted_provider="local",
    )

    assert session.model == "glm-5.1"
    assert session.model_provider == "ollama-cloud"


def test_stale_session_state_since_this_turn_started_is_not_clobbered():
    """If the session moved on since this turn's view of it, leave it alone."""
    session = _session(model="a-newer-pick", provider="ollama-cloud")
    routing = {
        "used_model": "qwen3.5:397b",
        "used_provider": "ollama-cloud",
        "provider_changed": True,
        "model_changed": True,
    }

    reconcile_session_provider_after_turn(
        session,
        routing,
        turn_owns_model=True,
        last_persisted_model="qwen3.6:35b-mlx",
        last_persisted_provider="local",
    )

    assert session.model == "a-newer-pick"
    assert session.model_provider == "ollama-cloud"


def test_missing_routing_is_a_no_op():
    session = _session()
    reconcile_session_provider_after_turn(
        session,
        None,
        turn_owns_model=True,
        last_persisted_model="qwen3.6:35b-mlx",
        last_persisted_provider="local",
    )
    assert session.model == "qwen3.6:35b-mlx"
    assert session.model_provider == "local"
