"""Fixture driven regression tests: the sample logs must stay useful."""

import json
import pathlib
import unittest

from logloom.analyzer import analyze
from logloom.parser import parse_text
from logloom.redaction import apply, detect
from logloom.report import render_json, render_report

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class MessyLogTests(unittest.TestCase):
    def setUp(self):
        self.lines = parse_text(load("messy.log"))
        self.analysis = analyze(self.lines)

    def test_it_parses(self):
        self.assertGreater(self.analysis.summary["total_lines"], 30)

    def test_it_finds_real_problems(self):
        labels = [issue.label for issue in self.analysis.issues]
        self.assertIn("Permission denied", labels)
        self.assertIn("Connection refused", labels)
        self.assertIn("Test failure", labels)

    def test_repeated_connection_failures_are_folded(self):
        connection = [
            issue for issue in self.analysis.issues if issue.label == "Connection refused"
        ][0]
        self.assertEqual(connection.count, 3)
        self.assertGreaterEqual(self.analysis.summary["duplicates"], 2)

    def test_download_noise_is_not_a_finding(self):
        labels = [issue.label for issue in self.analysis.issues]
        self.assertFalse([label for label in labels if "Downloaded" in label])

    def test_unicode_is_preserved_end_to_end(self):
        report = render_report(self.analysis, source="messy.log")
        self.assertIn("无法创建目标目录", report)

    def test_json_report_is_valid(self):
        payload = json.loads(render_json(self.analysis, source="messy.log"))
        self.assertTrue(payload["issues"])


class SecretsFixtureTests(unittest.TestCase):
    def setUp(self):
        self.text = load("secrets.log")
        self.lines = parse_text(self.text)
        self.findings = detect(self.lines)

    def rules(self):
        return {finding.rule for finding in self.findings}

    def test_expected_rules_are_detected(self):
        self.assertIn("basic_auth_url", self.rules())
        self.assertIn("aws_access_key", self.rules())
        self.assertIn("bearer_token", self.rules())

    def test_redacted_output_drops_the_credentials(self):
        redacted = apply([line.raw for line in self.lines], self.findings)
        joined = "\n".join(redacted)
        self.assertNotIn("hunter2placeholder", joined)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", joined)
        self.assertNotIn("abc123def456ghi789jkl012mno", joined)

    def test_redacted_report_has_no_credentials(self):
        analysis = analyze(self.lines)
        report = render_report(
            analysis, findings=self.findings, source="secrets.log", redacted=True
        )
        self.assertNotIn("hunter2placeholder", report)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", report)

    def test_stack_frames_are_attached_to_the_exception(self):
        analysis = analyze(self.lines)
        null_pointer = [
            issue for issue in analysis.issues if issue.label == "Null reference"
        ]
        self.assertEqual(len(null_pointer), 1)
        self.assertEqual(null_pointer[0].count, 3)
        self.assertTrue(null_pointer[0].context)


class AllFixtureFilesTests(unittest.TestCase):
    def test_every_fixture_is_analysable_and_renderable(self):
        for path in sorted(FIXTURES.glob("*.log")):
            with self.subTest(fixture=path.name):
                lines = parse_text(path.read_text(encoding="utf-8"))
                analysis = analyze(lines)
                report = render_report(
                    analysis, findings=detect(lines), source=path.name
                )
                self.assertIn("<!DOCTYPE html>", report)
                self.assertGreater(analysis.summary["total_lines"], 0)


if __name__ == "__main__":
    unittest.main()