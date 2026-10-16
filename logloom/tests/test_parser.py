import unittest

from logloom.parser import RANK, highest, parse_line, parse_text


class SeverityTests(unittest.TestCase):
    def test_bracketed_severity(self):
        line = parse_line(1, "[ERROR] something broke")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.message, "something broke")

    def test_colon_severity(self):
        line = parse_line(1, "ERROR: cannot find module 'example'")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.message, "cannot find module 'example'")

    def test_word_boundary_required(self):
        line = parse_line(1, "Errors were found in 3 files")
        self.assertEqual(line.severity, "log")

    def test_warning_and_fatal(self):
        self.assertEqual(parse_line(1, "WARNING: deprecated").severity, "warning")
        self.assertEqual(parse_line(1, "FATAL could not open").severity, "fatal")

    def test_glog_line(self):
        line = parse_line(1, "E0910 10:22:42.220  3301 build.rs:91] failed to acquire lock")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.message, "failed to acquire lock")
        self.assertEqual(line.timestamp, "0910 10:22:42.220")

    def test_pytest_progress_letter(self):
        line = parse_line(1, "E   ModuleNotFoundError: No module named 'app'")
        self.assertEqual(line.severity, "error")
        self.assertTrue(line.message.startswith("ModuleNotFoundError"))

    def test_pytest_assertion_diff_is_context_not_a_finding(self):
        line = parse_line(1, 'E        +  where 1 = cache.get("a")')
        self.assertEqual(line.kind, "trace")

    def test_parenthesised_logger_tag_is_stripped(self):
        line = parse_line(1, "[10:22:41.513] [ERROR] (web:1420): build failed")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.message, "build failed")

    def test_parenthesised_note_is_not_treated_as_a_logger_tag(self):
        line = parse_line(1, "Failed to connect (retrying in 5s)")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.raw, "Failed to connect (retrying in 5s)")
        self.assertIn("(retrying in 5s)", line.message)

    def test_highest_helper(self):
        self.assertEqual(highest("info", "error", "warning"), "error")
        self.assertEqual(highest(), "log")
        self.assertGreater(RANK["fatal"], RANK["log"])


class TimestampTests(unittest.TestCase):
    def test_iso_timestamp_in_brackets(self):
        line = parse_line(1, "[2024-05-02T11:22:33Z] [WARN] disk almost full")
        self.assertEqual(line.severity, "warning")
        self.assertEqual(line.timestamp, "2024-05-02T11:22:33Z")
        self.assertEqual(line.message, "disk almost full")

    def test_bare_timestamp(self):
        line = parse_line(1, "10:22:41.103 ERROR failed to load env")
        self.assertEqual(line.severity, "error")
        self.assertEqual(line.timestamp, "10:22:41.103")


class KindTests(unittest.TestCase):
    def test_blank_line(self):
        self.assertEqual(parse_line(1, "   ").kind, "blank")

    def test_header_line(self):
        self.assertEqual(parse_line(1, "========================== FAILURES ==========================").kind, "header")

    def test_python_trace_frame(self):
        line = parse_line(1, '  File "/app/tests/test_a.py", line 12, in test_a')
        self.assertEqual(line.kind, "trace")

    def test_javascript_trace_frame(self):
        line = parse_line(1, "    at loader (src/loader.js:42:11)")
        self.assertEqual(line.kind, "trace")

    def test_java_trace_frame(self):
        line = parse_line(1, "\tat com.example.Foo.bar(Foo.java:31)")
        self.assertEqual(line.kind, "trace")

    def test_caret_line_is_trace(self):
        self.assertEqual(parse_line(1, "      ^").kind, "trace")

    def test_indented_traceback_line_is_trace(self):
        line = parse_line(1, "    >       response = client.post('/api/payments')")
        self.assertEqual(line.kind, "trace")

    def test_plain_sentence_with_parentheses_is_not_trace(self):
        line = parse_line(1, "Failed to connect to database (retrying in 5s)")
        self.assertNotEqual(line.kind, "trace")

    def test_noise_lines(self):
        self.assertEqual(parse_line(1, "Downloading crate 'serde'").kind, "noise")
        self.assertEqual(parse_line(1, ".........").kind, "noise")

    def test_caused_by_is_an_error(self):
        line = parse_line(1, "Caused by: java.lang.NullPointerException")
        self.assertEqual(line.severity, "error")


class DocumentTests(unittest.TestCase):
    def test_ansi_is_stripped(self):
        line = parse_line(1, "\x1b[31mERROR\x1b[0m: it broke")
        self.assertNotIn("\x1b", line.raw)
        self.assertEqual(line.severity, "error")

    def test_line_numbers_are_one_based_and_contiguous(self):
        lines = parse_text("a\nb\nc")
        self.assertEqual([line.number for line in lines], [1, 2, 3])

    def test_unicode_is_preserved(self):
        lines = parse_text("ERROR: 未找到模块 'café' ✗")
        self.assertEqual(lines[0].message, "未找到模块 'café' ✗")

    def test_crlf_is_handled(self):
        lines = parse_text("first\r\nsecond\r\n")
        self.assertEqual([line.raw for line in lines], ["first", "second"])

    def test_parse_text_never_raises_on_empty(self):
        self.assertEqual(parse_text(""), [])


if __name__ == "__main__":
    unittest.main()