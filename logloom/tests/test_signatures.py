import unittest

from logloom.signatures import classify, extract_files, normalize, signature


class NormalizeTests(unittest.TestCase):
    def test_numbers_are_replaced(self):
        self.assertEqual(normalize("failed after 12 retries"), "failed after <n> retries")

    def test_quoted_strings_are_replaced(self):
        self.assertEqual(normalize("cannot find module 'app.users'"), "cannot find module <str>")

    def test_paths_are_replaced(self):
        self.assertEqual(normalize("at /home/dev/app/loader.py:42"), "at <path>:<n>")

    def test_windows_paths_are_replaced(self):
        self.assertEqual(normalize(r"at C:\build\app\loader.js:42"), "at <path>:<n>")

    def test_urls_and_uuids_are_replaced(self):
        text = "GET https://api.example.com/v1/users failed for 6f1d2a4e-1111-4222-8333-444444444444"
        normalized = normalize(text)
        self.assertIn("<url>", normalized)
        self.assertIn("<uuid>", normalized)

    def test_hex_addresses_are_replaced(self):
        self.assertEqual(normalize("segfault at 0xdeadbeef"), "segfault at <addr>")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(normalize("  too   many\tspaces "), "too many spaces")

    def test_normalizing_is_idempotent(self):
        once = normalize("ERROR at 10:22:41.103 for user 7")
        self.assertEqual(once, normalize(once))


class SignatureTests(unittest.TestCase):
    def test_same_problem_same_signature(self):
        first = "ERROR connection refused to 10.0.0.7:5432 after 3 attempts"
        second = "ERROR connection refused to 10.0.0.9:5432 after 7 attempts"
        self.assertEqual(signature(first), signature(second))

    def test_different_problems_differ(self):
        self.assertNotEqual(
            signature("connection refused to host a"),
            signature("permission denied on /tmp/x"),
        )

    def test_signature_is_short_and_stable(self):
        value = signature("ERROR boom")
        self.assertEqual(len(value), 12)
        self.assertEqual(value, signature("ERROR boom"))

    def test_empty_message_is_handled(self):
        self.assertTrue(signature(""))


class ClassifyTests(unittest.TestCase):
    def test_known_patterns_get_labels(self):
        cases = {
            "ModuleNotFoundError: No module named 'app'": "Missing module",
            "npm ERR! Cannot find module 'vite'": "Missing module",
            "EACCES: permission denied, open '/etc/hosts'": "Permission denied",
            "JavaScript heap out of memory": "Out of memory",
            "error: connection timed out after 30s": "Timeout",
            "Segmentation fault (core dumped)": "Process crash",
            "Address already in use :::8080": "Port already in use",
            "429 Too Many Requests": "Rate limited",
            "getaddrinfo: Name or service not known": "DNS failure",
            "DEPRECATIONWARNING: this API is deprecated": "Deprecation",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                result = classify(message)
                self.assertIsNotNone(result, message)
                self.assertEqual(result.label, expected)

    def test_unknown_message_returns_none(self):
        self.assertIsNone(classify("everything is fine, carrying on"))

    def test_failed_is_not_a_test_failure_on_its_own(self):
        # `FAILED` used to match "failed to resolve" and turned half a build log
        # into test failures.
        for message in (
            "failed to resolve: use of undeclared crate or module `tokio_util`",
            "error: build failed with 1 error",
            "Failed to load env: Error: ENOENT",
            "the build failed",
        ):
            with self.subTest(message=message):
                self.assertNotEqual(classify(message).label, "Test failure")

    def test_real_test_failures_are_still_detected(self):
        for message in (
            "FAILED tests/api/test_payments.py::test_charge_card_declined",
            "test result: FAILED. 12 passed; 3 failed; 0 ignored",
            "3 failed, 205 passed in 41.02s",
            "assert 1 == 2",
            "assert 'a' in rows",
            "AssertionError: assert 1 == 2",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify(message).label, "Test failure")

    def test_build_and_exit_conclusions(self):
        self.assertEqual(classify("error: could not compile `logloom` (lib)").label, "Build failed")
        self.assertEqual(classify("npm ERR! code ELIFECYCLE").label, "Build failed")
        self.assertEqual(classify("The process '/usr/bin/docker' aborted with exit code 1").label,
                         "Non-zero exit")
        self.assertEqual(classify("error: build step failed: command 'poetry build' exited with 2").label,
                         "Non-zero exit")

    def test_patterns_carry_a_severity(self):
        result = classify("ModuleNotFoundError: No module named 'app'")
        self.assertEqual(result.severity, "error")

    def test_empty_message_returns_none(self):
        self.assertIsNone(classify(""))


class ExtractFilesTests(unittest.TestCase):
    def test_finds_references(self):
        found = extract_files("> loader.py:42: raise ImportError (src/app.py:7)")
        self.assertIn("loader.py:42", found)
        self.assertIn("src/app.py:7", found)

    def test_returns_empty_list_when_absent(self):
        self.assertEqual(extract_files("no references here"), [])

    def test_results_are_deduplicated_and_limited(self):
        message = " ".join("file{}.py:{}".format(index, index) for index in range(20))
        self.assertLessEqual(len(extract_files(message, limit=3)), 3)


if __name__ == "__main__":
    unittest.main()