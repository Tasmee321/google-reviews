"""Run browser-extension network/barrier regressions with Node and no network."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for extension JavaScript tests")
class ExtensionNetworkJavaScriptTests(unittest.TestCase):
    def run_script(self, name):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / name)],
                                cwd=ROOT, capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_network_parser_and_probes(self):
        self.run_script("test_extension_network.js")

    def test_final_barrier_authorization_and_uncertain_retry_protection(self):
        self.run_script("test_extension_barrier.js")


if __name__ == "__main__":
    unittest.main()
