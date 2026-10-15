"""Tests never touch the network: any real request fails at once instead of waiting on a server."""
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to use the network; stub the fetch instead")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
