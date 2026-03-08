import pytest


# ── asyncio mode ──────────────────────────────────────────────────────────────
# Forces all async test functions to run under asyncio automatically.
# Requires: pytest-asyncio >= 0.21
#
# This means you do NOT need @pytest.mark.asyncio on every async test —
# just define `async def test_...` and pytest handles it.

pytest_plugins = ("pytest_asyncio",)