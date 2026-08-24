"""Persistence substrate shared by ARES's authoritative stores.

Currently the schema-migration runner (:mod:`core.store.migrations`). Kept
separate from ``core/memory`` and ``core/knowledge`` because it is used BY
both and must not depend on either.
"""
