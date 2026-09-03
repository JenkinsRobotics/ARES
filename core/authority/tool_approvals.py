"""Gate consequential mutations listed on Agent.approval_tools.

The field is stored on automation agent records. This helper is the shared
matcher so ARES can actually enforce it instead of only validating the list.
"""

from __future__ import annotations


def tool_requires_approval(approval_tools: object, tool: object) -> bool:
    """True when ``tool`` is listed as requiring an ARES approval.

    Matching is case-insensitive. Dotted capability names such as
    ``workspace.write`` match if the full name or the last segment is listed.
    An empty allowlist means this field gates nothing.
    """

    gated = {
        str(item).strip().lower()
        for item in (approval_tools or ())
        if str(item).strip()
    }
    raw = str(tool or "").strip().lower()
    if not raw or not gated:
        return False
    last = raw.rsplit(".", 1)[-1]
    candidates = {raw, last, raw.replace(".", "_"), raw.replace("_", ".")}
    return bool(gated & candidates)
