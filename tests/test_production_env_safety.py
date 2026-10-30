"""Regression checks for private production configuration and safe logs.

These static checks do not certify a deployed service or its credential history.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionEnvironmentSafetyTests(unittest.TestCase):
    def test_production_config_stays_private(self):
        self.assertFalse((ROOT / ".env.prod").exists())
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env.prod", ignored)
        self.assertIn(".env", ignored)
        self.assertTrue((ROOT / ".env.example").is_file())

    def test_init_never_logs_secret_prefix(self):
        source = (ROOT / "init-prod.sh").read_text(encoding="utf-8")
        self.assertNotIn('log_pass "$var = ${val:0:30}..."', source)
        self.assertIn('log_pass "$var configured (value withheld)"', source)

    def test_deploy_requires_private_environment(self):
        source = (ROOT / "deploy-prod.sh").read_text(encoding="utf-8")
        self.assertNotIn("cp .env.prod .env", source)
        self.assertIn('if [ ! -f .env ]; then', source)
        self.assertIn("create it privately from .env.example", source)

    def test_deployment_shell_syntax(self):
        for script in ("init-prod.sh", "deploy-prod.sh"):
            with self.subTest(script=script):
                checked = subprocess.run(
                    ["bash", "-n", str(ROOT / script)],
                    capture_output=True, text=True, check=False, timeout=10,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
