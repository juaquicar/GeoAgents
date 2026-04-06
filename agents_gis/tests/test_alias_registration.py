from unittest import TestCase
from unittest.mock import patch

from agents_gis import inspect as inspect_module
from agents_gis import service as service_module


class _DummyConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _DummyConnections:
    def __init__(self):
        self.databases = {}
        self._wrappers = {}

    def __getitem__(self, alias):
        self._wrappers.setdefault(alias, _DummyConn())
        return self._wrappers[alias]


class AgentAliasRegistrationTests(TestCase):
    def test_service_updates_existing_alias_config_and_closes_connection(self):
        connections = _DummyConnections()
        alias = "_agent_7__main"
        connections.databases[alias] = {"NAME": "old_db"}
        _ = connections[alias]

        conn_cfg = {
            "alias": "main",
            "db_name": "new_db",
            "host": "localhost",
            "port": 5432,
            "user": "u",
            "password": "p",
        }
        with patch.object(service_module, "connections", connections):
            returned_alias = service_module.get_or_register_agent_alias(7, conn_cfg)

        self.assertEqual(returned_alias, alias)
        self.assertEqual(connections.databases[alias]["NAME"], "new_db")
        self.assertTrue(connections[alias].closed)

    def test_inspect_keeps_existing_alias_when_config_is_unchanged(self):
        connections = _DummyConnections()
        alias = "_agent_9__gis"
        conn_cfg = {
            "alias": "gis",
            "db_name": "demo",
            "host": "localhost",
            "port": 5432,
            "user": "u",
            "password": "p",
        }
        expected_cfg = {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": "demo",
            "USER": "u",
            "PASSWORD": "p",
            "HOST": "localhost",
            "PORT": "5432",
            "CONN_MAX_AGE": 0,
            "ATOMIC_REQUESTS": False,
        }
        connections.databases[alias] = dict(expected_cfg)
        _ = connections[alias]

        with patch.object(inspect_module, "connections", connections):
            returned_alias = inspect_module.get_or_register_agent_alias(9, conn_cfg)

        self.assertEqual(returned_alias, alias)
        self.assertEqual(connections.databases[alias], expected_cfg)
        self.assertFalse(connections[alias].closed)
