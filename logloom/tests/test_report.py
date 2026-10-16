import json
import re
import unittest
from html.parser import HTMLParser

from logloom.analyzer import analyze_text
from logloom.parser import parse_text
from logloom.redaction import detect
from logloom.report import render_json, render_report, template_path

SAMPLE = """
INFO starting build
ERROR cannot find module 'app'
    at loader (src/loader.js:42:11)
ERROR cannot find module 'app'
    at loader (src/loader.js:42:11)
WARN deprecated api used
INFO done
""".strip()

XSS = 'ERROR <script>alert("xss")</script> & "quoted" <b>bold</b>'


class BalanceChecker(HTMLParser):
    """Very small well-formedness check for the generated document."""

    VOID = {"meta", "input", "br", "hr", "img", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append("stray </{}>".format(tag))
        elif self.stack[-1] != tag:
            self.errors.append("expected </{}>, got </{}>".format(self.stack[-1], tag))
            self.stack.pop()
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


class TemplateTests(unittest.TestCase):
    def test_template_exists_and_has_placeholders(self):
        text = template_path().read_text(encoding="utf-8")
        for token in ("{{TITLE}}", "{{ISSUES}}", "{{RAW}}", "{{STATS}}"):
            self.assertIn(token, text)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.lines = parse_text(SAMPLE)
        self.analysis = analyze_text(SAMPLE)
        self.report = render_report(self.analysis, source="build.log", version="0.1.0")

    def test_document_is_balanced(self):
        checker = BalanceChecker()
        checker.feed(self.report)
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [])

    def test_no_unreplaced_tokens(self):
        self.assertEqual(re.findall(r"\{\{[A-Z_]+\}\}", self.report), [])

    def test_findings_are_rendered(self):
        self.assertIn("Missing module", self.report)
        self.assertIn('class="sev error"', self.report)

    def test_raw_lines_keep_their_numbers(self):
        self.assertIn(">1</span>", self.report.replace('data-ln="1"', '>1</span>'))
        self.assertIn("INFO starting build", self.report)

    def test_occurrence_counts_are_shown(self):
        self.assertIn("× 2", self.report)

    def test_title_and_source_are_escaped(self):
        report = render_report(self.analysis, source='<b>log</b>', title="T")
        self.assertNotIn("<b>log</b>", report)
        self.assertIn("&lt;b&gt;log&lt;/b&gt;", report)

    def test_clean_log_renders_an_empty_state(self):
        analysis = analyze_text("INFO all good\n")
        report = render_report(analysis, source="ok.log")
        self.assertIn("No failures matched", report)

    def test_no_raw_omits_raw_output(self):
        report = render_report(self.analysis, source="build.log", include_raw=False)
        self.assertNotIn('class="raw"', report)
        self.assertIn("Raw output omitted", report)

    def test_unknown_severity_is_mapped(self):
        analysis = analyze_text("INFO plain note\n", include_info=True, min_severity="log")
        report = render_report(analysis, source="x.log")
        self.assertIn('class="sev info"', report)


class EscapingTests(unittest.TestCase):
    def test_script_tags_from_input_are_neutralised(self):
        analysis = analyze_text(XSS, include_info=True, min_severity="log")
        report = render_report(analysis, source="xss.log")
        body = report.split("<body>", 1)[1]
        self.assertNotIn("<script>alert", body)
        self.assertIn("&lt;script&gt;", body)

    def test_input_cannot_close_the_script_tag_of_the_template(self):
        analysis = analyze_text("ERROR </script><script>alert(1)</script>", include_info=True,
                                min_severity="log")
        report = render_report(analysis, source="x.log")
        body = report.split("<body>", 1)[1]
        self.assertNotIn("</script><script>alert", body)


class SecretRenderingTests(unittest.TestCase):
    def setUp(self):
        text = "INFO key=AKIAIOSFODNN7EXAMPLE\nERROR failed\n"
        self.lines = parse_text(text)
        self.analysis = analyze_text(text)
        self.findings = detect(self.lines)

    def test_findings_add_a_review_section(self):
        report = render_report(self.analysis, findings=self.findings, source="s.log")
        self.assertIn("Potential secrets", report)
        self.assertIn("aws_access_key", report)
        self.assertIn("Contains secrets", report)

    def test_redacted_report_contains_no_secret(self):
        report = render_report(
            self.analysis, findings=self.findings, source="s.log", redacted=True
        )
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", report)
        self.assertIn("[REDACTED:aws_access_key]", report)
        self.assertIn("Redacted copy", report)
        self.assertNotIn('id="redact"', report)

    def test_unredacted_report_marks_but_keeps_the_secret(self):
        report = render_report(self.analysis, findings=self.findings, source="s.log")
        self.assertIn('class="secret"', report)
        self.assertIn("AKIAIOSFODNN7EXAMPLE", report)
        self.assertIn('id="redact"', report)

    def test_finding_titles_are_covered_by_the_redaction_toggle(self):
        text = "WARN [api] header contained Bearer abc123def456ghi789jkl012mno\n"
        lines = parse_text(text)
        analysis = analyze_text(text)
        findings = detect(lines)
        report = render_report(analysis, findings=findings, source="s.log")
        # The secret appears inside a generated title, so it must be wrapped in
        # a toggleable span rather than printed as plain text.
        self.assertIn('class="secret" data-rule="bearer_token"', report)
        self.assertGreaterEqual(report.count("abc123def456ghi789jkl012mno"), 2)

    def test_redacted_report_scrubs_titles_too(self):
        text = "WARN [api] header contained Bearer abc123def456ghi789jkl012mno\n"
        analysis = analyze_text(text)
        report = render_report(
            analysis, findings=detect(parse_text(text)), source="s.log", redacted=True
        )
        self.assertNotIn("abc123def456ghi789jkl012mno", report)

    def test_no_secret_findings_shows_the_clear_banner(self):
        analysis = analyze_text("ERROR nothing sensitive here\n")
        report = render_report(analysis, findings=[], source="s.log")
        self.assertIn("No secrets detected", report)
        self.assertNotIn("Potential secrets", report)

    def test_document_stays_balanced_with_secrets(self):
        report = render_report(self.analysis, findings=self.findings, source="s.log")
        checker = BalanceChecker()
        checker.feed(report)
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [])


class JsonTests(unittest.TestCase):
    def setUp(self):
        self.analysis = analyze_text(SAMPLE)
        self.payload = json.loads(render_json(self.analysis, source="build.log"))

    def test_payload_shape(self):
        self.assertEqual(self.payload["tool"], "logloom")
        self.assertEqual(self.payload["source"], "build.log")
        self.assertIn("summary", self.payload)
        self.assertIsInstance(self.payload["issues"], list)
        self.assertTrue(self.payload["issues"])

    def test_issue_entries_have_expected_keys(self):
        issue = self.payload["issues"][0]
        for key in ("signature", "label", "severity", "count", "occurrences", "context"):
            self.assertIn(key, issue)

    def test_json_is_serialisable_with_unicode(self):
        analysis = analyze_text("ERROR 未找到模块 'café'\n")
        payload = json.loads(render_json(analysis, source="unicode.log"))
        self.assertIn("未找到模块", json.dumps(payload, ensure_ascii=False))


class TemplateScriptTests(unittest.TestCase):
    """The report script must register handlers before its first pass runs.

    A load-order slip here silently disables the redaction toggle, and no Python
    unit test can catch it, so the ordering requirement is asserted directly.
    """

    def setUp(self):
        text = template_path().read_text(encoding="utf-8")
        self.script = text[text.index("(function ()") :]

    def test_first_pass_runs_after_handlers_are_registered(self):
        first_pass = self.script.index("\n  apply();")
        for handler in (
            "q.addEventListener",
            "filters.addEventListener",
            "toggleAll.addEventListener",
            "redact.addEventListener",
            "document.getElementById('download').addEventListener",
        ):
            with self.subTest(handler=handler):
                self.assertLess(
                    self.script.index(handler), first_pass, "handler registered after apply()"
                )

    def test_definitions_the_first_pass_depends_on_come_first(self):
        first_pass = self.script.index("\n  apply();")
        for name in ("var toggleAll", "function syncToggleLabel", "var redact"):
            with self.subTest(name=name):
                self.assertLess(self.script.index(name), first_pass)


class ExampleTests(unittest.TestCase):
    def test_bundled_examples_parse(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        for name in ("failed-tests.log", "failed-build.log"):
            path = root / "examples" / name
            self.assertTrue(path.is_file(), path)
            analysis = analyze_text(path.read_text(encoding="utf-8"))
            self.assertGreater(analysis.summary["issue_count"], 0)
            self.assertGreater(analysis.summary["errors"], 0)

    def test_build_example_has_no_false_positive_secrets(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        text = (root / "examples" / "failed-build.log").read_text(encoding="utf-8")
        # npm package names (`request@2.88.2`, `@logloom/web`) used to match the
        # email rule and made a clean log report four "potential secrets".
        self.assertEqual(detect(parse_text(text)), [])

    def test_secrets_fixture_is_where_detection_is_demonstrated(self):
        import pathlib

        fixture = pathlib.Path(__file__).resolve().parent / "fixtures" / "secrets.log"
        rules = {f.rule for f in detect(parse_text(fixture.read_text(encoding="utf-8")))}
        self.assertIn("aws_access_key", rules)
        self.assertIn("basic_auth_url", rules)


if __name__ == "__main__":
    unittest.main()