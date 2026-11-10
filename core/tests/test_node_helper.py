"""`require_node`: a skip on a laptop, a failure in CI."""

import unittest
from unittest import mock

from django.test import SimpleTestCase

from core.tests import node


class RequireNodeTests(SimpleTestCase):
    def test_with_node_it_lets_the_test_run(self):
        with mock.patch.object(node, "node_available", return_value=True):
            self.assertIsNone(node.require_node())

    def test_without_node_a_laptop_skips(self):
        with mock.patch.object(node, "node_available", return_value=False):
            for environ in ({}, {"CI": "false"}, {"CI": "0"}, {"CI": ""}):
                with self.subTest(environ=environ):
                    with mock.patch.dict("os.environ", environ, clear=True):
                        with self.assertRaises(unittest.SkipTest):
                            node.require_node()

    def test_without_node_ci_fails(self):
        """A skip there is a pass nobody saw: these are the only checks
        that the client's filters and the server's agree."""
        with mock.patch.object(node, "node_available", return_value=False):
            with mock.patch.dict("os.environ", {"CI": "true"}):
                with self.assertRaisesMessage(AssertionError, "CI must run"):
                    node.require_node()
