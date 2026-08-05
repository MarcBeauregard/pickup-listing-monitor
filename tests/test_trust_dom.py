import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrustDomTests(unittest.TestCase):
    def test_complete_partial_and_empty_dom_states(self):
        result = subprocess.run(
            ["node", "--test", str(ROOT / "tests/trust-rendering.test.cjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
