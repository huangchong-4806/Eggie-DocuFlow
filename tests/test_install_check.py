import io
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from core.install_check import _check_update_signature
from main import main


class InstallSignatureTests(unittest.TestCase):
    def test_offline_fixture_passes_the_real_verifier(self):
        _check_update_signature()

    def test_install_command_fails_when_verifier_is_missing(self):
        verifier = "cryptography.hazmat.primitives.asymmetric.ed25519"
        errors = io.StringIO()
        with patch.dict(sys.modules, {verifier: None}), patch.object(
            sys, "argv", ["Eggie", "--check-install"]
        ), redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
            main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("Update signature self-check failed", errors.getvalue())
