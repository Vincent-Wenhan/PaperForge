from __future__ import annotations

import pytest

from paperforge.agents.browser_smoke import run_browser_smoke


@pytest.mark.asyncio
async def test_browser_smoke_without_acceptance_criteria_is_explicitly_passed(tmp_path):
    result = await run_browser_smoke("http://127.0.0.1:1/", None, tmp_path)

    assert result["status"] == "passed"
    assert result["checks"] == []
