import pytest

from integration.tests.indexers_comparison.constants import ENVS
from utils.apiclient import JsonRPCSession


@pytest.fixture
def endpoints():
    clients = []
    for env in ENVS:
        clients.append({"name": env["name"], "client": JsonRPCSession(env["url"])})
    return clients
