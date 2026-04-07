"""
Tests del registro de aliases de BD en el service GIS.
Verifica que get_or_register_agent_alias registra, actualiza y cierra conexiones correctamente.

Ejecutar:
    python manage.py test tests.test_gis_alias
"""
from unittest import TestCase
from unittest.mock import patch

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
        # Simular el atributo _connections que usa delattr en service.py
        self._connections = self

    def __getitem__(self, alias):
        self._wrappers.setdefault(alias, _DummyConn())
        return self._wrappers[alias]

    def get(self, alias, default=None):
        return self.databases.get(alias, default)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        # Simula el delattr del wrapper cacheado sin lanzar error
        pass


class AgentAliasRegistrationTests(TestCase):
    def test_service_updates_existing_alias_config_and_closes_connection(self):
        """Al cambiar la config, debe actualizar el alias y cerrar la conexión anterior."""
        connections = _DummyConnections()
        alias = "_agent_7__main"
        connections.databases[alias] = {"NAME": "old_db"}
        _ = connections[alias]  # crea el wrapper

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
        # La conexión anterior debe haberse cerrado
        self.assertTrue(connections[alias].closed)

    def test_service_keeps_existing_alias_when_config_is_unchanged(self):
        """Si la config no cambia, no debe cerrar ni recrear la conexión."""
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

        # Pre-registrar exactamente la misma config que devuelve _make_agent_db_cfg
        expected_cfg = service_module._make_agent_db_cfg(conn_cfg)
        connections.databases[alias] = dict(expected_cfg)
        wrapper = connections[alias]  # crea el wrapper

        with patch.object(service_module, "connections", connections):
            returned_alias = service_module.get_or_register_agent_alias(9, conn_cfg)

        self.assertEqual(returned_alias, alias)
        self.assertEqual(connections.databases[alias], expected_cfg)
        # La conexión NO debe haberse cerrado (config sin cambios)
        self.assertFalse(wrapper.closed)

    def test_service_registers_new_alias_when_not_present(self):
        """Registrar un alias que no existe debe añadirlo a connections.databases."""
        connections = _DummyConnections()
        conn_cfg = {
            "alias": "remote",
            "db_name": "tesa",
            "host": "82.223.78.166",
            "port": 5432,
            "user": "postgres",
            "password": "",
            "schema": "planex",
        }

        with patch.object(service_module, "connections", connections):
            returned_alias = service_module.get_or_register_agent_alias(42, conn_cfg)

        expected_alias = "_agent_42__remote"
        self.assertEqual(returned_alias, expected_alias)
        self.assertIn(expected_alias, connections.databases)
        self.assertEqual(connections.databases[expected_alias]["NAME"], "tesa")
        self.assertEqual(connections.databases[expected_alias]["HOST"], "82.223.78.166")
        self.assertEqual(connections.databases[expected_alias]["PORT"], "5432")
