from django.test import SimpleTestCase

from agents_core.heuristics import normalize_goal, build_goal_signature


class HeuristicsTextTests(SimpleTestCase):
    def test_normalize_goal_removes_accents(self):
        self.assertEqual(normalize_goal("Trázame una ruta"), "trazame una ruta")

    def test_build_goal_signature_uses_keywords(self):
        signature = build_goal_signature("Traza una ruta de red entre dos puntos")
        self.assertIn("traza", signature)
        self.assertIn("ruta", signature)