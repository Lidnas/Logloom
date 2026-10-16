import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from logloom.cli import EXIT_FINDINGS, EXIT_INPUT_ERROR, EXIT_OK, main

LOG = """INFO starting build
ERROR cannot find module 'app'
    at loader (src/loader.js:42:11)
WARN deprecated api
ERROR cannot find module 'app'
INFO done
"""

SECRET_LOG = "INFO using AKIAIOSFODNN7EXAMPLE\nERROR failed to reach host\n"


def run(argv, stdin_text=""):
    """Run the CLI with captured streams; returns (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    stdin = io.StringIO(stdin_text)
    with mock.patch.object(sys, "stdin", stdin):
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
    return code, out.getvalue(), err.getvalue()


class AnalyzeFileTests(unittest.TestCase):
    def setUp(self):
        handle, self.log_path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(LOG)
        self.tmpdir = tempfile.mkdtemp()
        self.out_path = os.path.join(self.tmpdir, "report.html")

    def test_writes_report_and_returns_zero(self):
        code, out, err = run(["analyze", self.log_path, "--output", self.out_path])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(os.path.isfile(self.out_path))
        with open(self.out_path, encoding="utf-8") as stream:
            content = stream.read()
        self.assertIn("Missing module", content)
        self.assertIn("INFO starting build", content)

    def test_diagnostics_go_to_stderr_only(self):
        code, out, err = run(["analyze", self.log_path, "--output", self.out_path])
        self.assertEqual(out, "")
        self.assertIn("logloom: wrote", err)
        self.assertIn("findings", err)

    def test_quiet_suppresses_the_summary(self):
        code, out, err = run(
            ["analyze", self.log_path, "--output", self.out_path, "--quiet"]
        )
        self.assertEqual(err, "")

    def test_title_can_be_overridden(self):
        run(["analyze", self.log_path, "--output", self.out_path, "--title", "My build"])
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertIn("My build", stream.read())

    def test_no_raw_omits_the_raw_section(self):
        run(["analyze", self.log_path, "--output", self.out_path, "--no-raw"])
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertIn("Raw output omitted", stream.read())

    def test_missing_input_returns_input_error(self):
        code, out, err = run(
            ["analyze", os.path.join(self.tmpdir, "nope.log"), "--output", self.out_path]
        )
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("cannot read input", err)

    def test_fail_on_error_changes_the_exit_code(self):
        code, _, _ = run(
            ["analyze", self.log_path, "--output", self.out_path, "--fail-on", "error"]
        )
        self.assertEqual(code, EXIT_FINDINGS)

    def test_fail_on_never_is_the_default(self):
        code, _, _ = run(["analyze", self.log_path, "--output", self.out_path])
        self.assertEqual(code, EXIT_OK)


class StdinTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.out_path = os.path.join(self.tmpdir, "report.html")

    def test_dash_reads_stdin(self):
        code, out, err = run(["analyze", "-", "--output", self.out_path], LOG)
        self.assertEqual(code, EXIT_OK)
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertIn("INFO starting build", stream.read())

    def test_omitted_path_reads_stdin(self):
        code, _, _ = run(["analyze", "--output", self.out_path], LOG)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(os.path.isfile(self.out_path))

    def test_progress_messages_do_not_leak_into_stdout(self):
        code, out, _ = run(["analyze", "-", "--output", self.out_path], LOG)
        self.assertEqual(out, "")

    def test_source_is_labelled_stdin(self):
        run(["analyze", "-", "--output", self.out_path], LOG)
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertIn("stdin", stream.read())

    def test_empty_stdin_is_handled(self):
        code, _, _ = run(["analyze", "-", "--output", self.out_path], "")
        self.assertEqual(code, EXIT_OK)
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertIn("No failures matched", stream.read())

    def test_invalid_utf8_is_replaced(self):
        handle, path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(handle, "wb") as stream:
            stream.write(b"ERROR broken byte \xff\xfe here\n")
        code, _, _ = run(["analyze", path, "--output", self.out_path])
        self.assertEqual(code, EXIT_OK)


class JsonFormatTests(unittest.TestCase):
    def setUp(self):
        handle, self.log_path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(LOG)
        self.tmpdir = tempfile.mkdtemp()
        self.out_path = os.path.join(self.tmpdir, "report.json")

    def test_json_goes_to_stdout(self):
        code, out, err = run(["analyze", self.log_path, "--format", "json"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["tool"], "logloom")
        self.assertIn("issues", payload)
        self.assertIn("summary", payload)

    def test_json_can_be_written_to_a_file(self):
        run(["analyze", self.log_path, "--format", "json", "--output", self.out_path, "--quiet"])
        with open(self.out_path, encoding="utf-8") as stream:
            self.assertEqual(json.load(stream)["tool"], "logloom")

    def test_stdout_flag_prints_html(self):
        code, out, _ = run(["analyze", self.log_path, "--stdout", "--quiet"])
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn("Missing module", out)


class RedactionFlagTests(unittest.TestCase):
    def setUp(self):
        handle, self.log_path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(SECRET_LOG)
        self.tmpdir = tempfile.mkdtemp()
        self.out_path = os.path.join(self.tmpdir, "report.html")

    def test_default_report_flags_the_secret(self):
        run(["analyze", self.log_path, "--output", self.out_path, "--quiet"])
        with open(self.out_path, encoding="utf-8") as stream:
            content = stream.read()
        self.assertIn("AKIAIOSFODNN7EXAMPLE", content)
        self.assertIn("Contains secrets", content)

    def test_redact_flag_removes_the_secret(self):
        run(["analyze", self.log_path, "--output", self.out_path, "--redact", "--quiet"])
        with open(self.out_path, encoding="utf-8") as stream:
            content = stream.read()
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", content)
        self.assertIn("[REDACTED:aws_access_key]", content)

    def test_redact_flag_reports_the_count(self):
        _, _, err = run(["analyze", self.log_path, "--output", self.out_path, "--redact"])
        self.assertIn("potential secret", err.lower())


class UsageTests(unittest.TestCase):
    def test_no_command_prints_help(self):
        code, out, err = run([])
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("usage", err.lower())
        self.assertEqual(out, "")

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as raised:
            with mock.patch.object(sys, "stdout", io.StringIO()):
                main(["--version"])
        self.assertEqual(raised.exception.code, 0)

    def test_unknown_flag_exits_with_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            with mock.patch.object(sys, "stderr", io.StringIO()):
                main(["analyze", "--bogus"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()