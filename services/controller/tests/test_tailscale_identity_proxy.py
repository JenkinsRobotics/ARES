from tailscale_identity_proxy import authorized


def test_identity_proxy_is_exact_user_and_tailnet_host_only():
    allowed = "owner@example.com,second@example.com"
    assert authorized("mac.tailnet.ts.net", "OWNER@example.com", allowed)
    assert authorized("mac.tailnet.ts.net:443", "second@example.com", allowed)
    assert not authorized("mac.tailnet.ts.net", "other@example.com", allowed)
    assert not authorized("127.0.0.1:8786", "owner@example.com", allowed)
    assert not authorized("mac.tailnet.ts.net", "", allowed)
