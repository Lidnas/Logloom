import unittest

from logloom.redaction import apply, detect, detect_text

SECRET_LOG = """INFO starting build
DEBUG using credentials: AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
DEBUG registry token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
ERROR connecting to postgres://admin:sup3rs3cret@db.internal:5432/app
INFO loaded config
WARN session secret="s3cr3t-value-1234" for user dev@example.com
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAx0Z0N9QnQeJ8k1oV2b3c4d5e6f7g8h9i0j
-----END RSA PRIVATE KEY-----
INFO done
"""


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.findings = detect_text(SECRET_LOG)

    def rules(self):
        return [finding.rule for finding in self.findings]

    def test_detects_known_secret_types(self):
        rules = self.rules()
        for expected in (
            "aws_access_key",
            "github_token",
            "basic_auth_url",
            "private_key",
            "password_assignment",
        ):
            self.assertIn(expected, rules)

    def test_clean_log_has_no_findings(self):
        self.assertEqual(detect_text("INFO build ok\nWARN 3 warnings\n"), [])

    def test_offsets_point_at_the_secret(self):
        lines = SECRET_LOG.split("\n")
        for finding in self.findings:
            if finding.spans_lines:
                continue
            line = lines[finding.line_number - 1]
            self.assertEqual(line[finding.start : finding.end], finding.text)

    def test_multiline_secret_covers_every_line_it_spans(self):
        keys = [finding for finding in self.findings if finding.rule == "private_key"]
        self.assertEqual(len(keys), 1)
        key = keys[0]
        self.assertTrue(key.spans_lines)
        self.assertEqual(SECRET_LOG.split("\n")[key.line_number - 1][key.start :], "-----BEGIN RSA PRIVATE KEY-----")
        output = apply(SECRET_LOG.split("\n"), [key])
        joined = "\n".join(output)
        self.assertNotIn("MIIEowIBAAKCAQEAx0Z0N9QnQeJ8k1oV2b3c4d5e6f7g8h9i0j", joined)
        self.assertNotIn("-----END RSA PRIVATE KEY-----", joined)

    def test_overlapping_matches_are_not_duplicated(self):
        spans = [
            (finding.line_number, finding.start, finding.end)
            for finding in self.findings
            if finding.rule == "basic_auth_url"
        ]
        self.assertEqual(len(spans), 1)
        line = SECRET_LOG.split("\n")[3]
        self.assertTrue(line[spans[0][1] : spans[0][2]].startswith("postgres://"))

    def test_email_is_low_confidence_and_opt_in(self):
        emails = [finding for finding in self.findings if finding.rule == "email"]
        self.assertTrue(emails)
        self.assertEqual(emails[0].confidence, "low")
        self.assertFalse(emails[0].redact_by_default)

    def test_preview_never_shows_the_whole_secret(self):
        for finding in self.findings:
            self.assertNotEqual(finding.preview, finding.text)

    def test_marker_names_the_rule(self):
        for finding in self.findings:
            self.assertIn(finding.rule, finding.marker)

    def test_detection_on_parsed_lines_matches_text(self):
        from logloom.parser import parse_text

        self.assertEqual(detect(parse_text(SECRET_LOG)), self.findings)

    def test_short_lines_are_skipped(self):
        self.assertEqual(detect_text("a b c d e f g\n"), [])

    def test_findings_are_ordered_by_line(self):
        numbers = [finding.line_number for finding in self.findings]
        self.assertEqual(numbers, sorted(numbers))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.lines = SECRET_LOG.split("\n")
        self.findings = detect_text(SECRET_LOG)

    def test_secrets_are_replaced_with_markers(self):
        output = apply(self.lines, self.findings)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", "\n".join(output))
        self.assertIn("[REDACTED:aws_access_key]", output[1])
        self.assertIn("[REDACTED:github_token]", output[2])

    def test_other_lines_are_untouched(self):
        output = apply(self.lines, self.findings)
        self.assertEqual(output[0], "INFO starting build")
        self.assertEqual(output[4], "INFO loaded config")

    def test_apply_is_selective(self):
        subset = [f for f in self.findings if f.rule == "aws_access_key"]
        output = apply(self.lines, subset)
        joined = "\n".join(output)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", joined)
        self.assertIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", joined)

    def test_apply_without_findings_is_identity(self):
        self.assertEqual(apply(self.lines, []), self.lines)

    def test_line_count_is_preserved(self):
        output = apply(self.lines, self.findings)
        self.assertEqual(len(output), len(self.lines))

    def test_apply_handles_empty_input(self):
        self.assertEqual(apply([], []), [])


class FalsePositiveTests(unittest.TestCase):
    def test_npm_package_names_are_not_emails(self):
        text = (
            "npm WARN deprecated request@2.88.2: request has been deprecated\n"
            "npm WARN deprecated tough-cookie@4.1.3: tough-cookie has been deprecated\n"
            "npm ERR! @logloom/web@0.1.0 build: `vite build`\n"
            "npm ERR!   logloom@0.1.0 dev\n"
        )
        self.assertEqual(detect_text(text), [])

    def test_real_addresses_still_match(self):
        self.assertEqual([f.rule for f in detect_text("contact dev@example.com now")], ["email"])

    def test_urls_and_paths_are_not_secrets(self):
        text = "GET https://github.com/request/request/issues/3142 failed\n"
        self.assertEqual(detect_text(text), [])


if __name__ == "__main__":
    unittest.main()