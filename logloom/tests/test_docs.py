"""Keep README.md honest: docs must match the code they describe."""

import pathlib
import re
import unittest

from logloom.redaction import RULES
from logloom.signatures import PATTERNS

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


class ReadmeTests(unittest.TestCase):
    def test_every_pattern_label_is_documented(self):
        documented = set(re.findall(r"\| \*\*([^*|]+)\*\*", README))
        for _, classification in PATTERNS:
            with self.subTest(label=classification.label):
                self.assertIn(classification.label, documented)

    def test_every_secret_rule_is_documented(self):
        documented = set(re.findall(r"\| `([a-z_]+)` \|", README))
        for rule in RULES:
            with self.subTest(rule=rule.name):
                self.assertIn(rule.name, documented)

    def test_every_cli_option_is_documented(self):
        from logloom.cli import build_parser

        options = set()
        for action in build_parser()._subparsers._group_actions[0].choices["analyze"]._actions:
            options.update(action.option_strings)
        for option in sorted(options):
            if option in ("-h", "--help"):
                continue
            with self.subTest(option=option):
                self.assertIn("`{}`".format(option), README)

    def test_generated_blocks_are_present(self):
        self.assertIn("<!-- BEGIN GENERATED: patterns -->", README)
        self.assertIn("<!-- END GENERATED: secrets -->", README)

    def test_secrets_warning_is_present(self):
        # The single most important caveat in the project.
        self.assertIn("Without `--redact`, the report file contains", README)

    def test_benchmark_methodology_is_documented(self):
        self.assertIn("python bench.py", README)
        self.assertIn("Methodology", README)

    def test_screenshots_exist(self):
        images = ROOT / "docs" / "images"
        for name in ("report-findings.png", "report-secrets.png", "report-dark.png"):
            with self.subTest(image=name):
                path = images / name
                self.assertTrue(path.is_file(), path)
                self.assertIn("docs/images/" + name, README)


if __name__ == "__main__":
    unittest.main()