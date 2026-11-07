"""Fixtures: custom integrations on, and the real Phone remote add-on with a fake TV behind it."""

from __future__ import annotations

import pytest

from .harness import Addon


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def addon(socket_enabled):
    a = await Addon().start()
    yield a
    await a.stop()
