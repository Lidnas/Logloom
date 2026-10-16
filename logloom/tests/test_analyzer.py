import unittest

from logloom.analyzer import analyze, analyze_text
from logloom.parser import parse_text

REPEATED = """
INFO starting build
Compiling crate a
ERROR connection refused to 10.0.0.7:5432 after 3 attempts
WARNING retrying
ERROR connection refused to 10.0.0.9:5432 after 7 attempts
Compiling crate b
ERROR connection refused to 10.0.0.8:5432 after 1 attempts
INFO done
""".strip()


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.analysis = analyze_text(REPEATED)

    def test_repeated_failures_collapse_into_one_issue(self):
        self.assertEqual(self.analysis.summary["issue_count"], 2)
        connection = [i for i in self.analysis.issues if i.label == "Connection refused"][0]
        self.assertEqual(connection.count, 3)
        self.assertEqual(connection.occurrences, [3, 5, 7])

    def test_first_and_last_line_are_tracked(self):
        connection = [i for i in self.analysis.issues if i.label == "Connection refused"][0]
        self.assertEqual(connection.first_line, 3)
        self.assertEqual(connection.last_line, 7)

    def test_duplicate_count_is_reported(self):
        self.assertEqual(self.analysis.summary["duplicates"], 2)

    def test_ordinary_lines_are_not_findings(self):
        labels = [issue.label for issue in self.analysis.issues]
        self.assertNotIn("starting build", labels)
        self.assertGreater(self.analysis.summary["other_groups"], 0)

    def test_include_info_surfaces_everything(self):
        analysis = analyze_text(REPEATED, include_info=True, min_severity="log")
        self.assertGreater(analysis.summary["issue_count"], self.analysis.summary["issue_count"])

    def test_summary_counts(self):
        summary = self.analysis.summary
        self.assertEqual(summary["total_lines"], 8)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["first_failure"], 3)

    def test_issues_are_sorted_by_severity_then_count(self):
        severities = [issue.severity for issue in self.analysis.issues]
        self.assertEqual(severities[0], "error")

    def test_every_group_keeps_its_original_line_numbers(self):
        for issue in self.analysis.issues:
            for number in issue.occurrences:
                self.assertTrue(1 <= number <= self.analysis.summary["total_lines"])

    def test_file_references_are_collected(self):
        analysis = analyze_text("ERROR cannot open config file at /srv/app/config.yaml:12")
        issue = analysis.issues[0]
        self.assertTrue(any("config.yaml:12" in ref for ref in issue.files))


class TraceTests(unittest.TestCase):
    def test_frames_attach_to_the_preceding_issue(self):
        text = (
            "ERROR NullPointerException: service was null\n"
            '  File "/app/run.py", line 12, in run\n'
            "    return service.start()\n"
            "INFO finished\n"
        )
        analysis = analyze_text(text)
        issue = analysis.issues[0]
        self.assertEqual(issue.label, "Null reference")
        self.assertEqual(len(issue.context), 2)
        self.assertEqual(issue.context[0][0], 2)

    def test_trace_after_a_noise_line_does_not_attach(self):
        text = "Compiling crate a\n  File \"/app/run.py\", line 12, in run\n"
        analysis = analyze_text(text)
        self.assertEqual(analysis.issues, [])
        self.assertEqual(analysis.summary["trace_lines"], 1)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_input(self):
        analysis = analyze_text("")
        self.assertEqual(analysis.issues, [])
        self.assertIsNone(analysis.summary["first_failure"])
        self.assertEqual(analysis.summary["total_lines"], 0)

    def test_clean_log_has_no_findings(self):
        analysis = analyze_text("INFO server started on port 8080\nINFO ready\n")
        self.assertEqual(analysis.issues, [])
        self.assertEqual(analysis.summary["total_lines"], 2)

    def test_min_severity_filter(self):
        analysis = analyze_text(REPEATED, min_severity="error")
        self.assertEqual(analysis.summary["issue_count"], 1)

    def test_occurrence_cap(self):
        text = "\n".join("ERROR failure {}".format(index) for index in range(100))
        issue = analyze_text(text).issues[0]
        self.assertEqual(issue.count, 100)
        self.assertEqual(issue.occurrences_shown, 60)
        self.assertEqual(issue.occurrences_hidden, 40)

    def test_large_input_is_handled(self):
        text = "\n".join("WARN retry {}".format(index % 7) for index in range(20000))
        analysis = analyze(parse_text(text))
        self.assertEqual(analysis.summary["issue_count"], 1)
        self.assertEqual(analysis.issues[0].count, 20000)


class CoalesceTests(unittest.TestCase):
    """One build failure reported five ways is one card, not five."""

    TEXT = (
        "INFO starting\n"
        "error: ELIFECYCLE Command failed\n"
        "INFO compiling\n"
        "npm ERR! code ELIFECYCLE\n"
        "npm ERR! errno 1\n"
        "INFO linking\n"
        "error: could not compile `app` (lib) due to 3 previous errors\n"
        "INFO done\n"
    )

    def setUp(self):
        self.analysis = analyze_text(self.TEXT)

    def test_same_label_merges_into_one_finding(self):
        build_failed = [i for i in self.analysis.issues if i.label == "Build failed"]
        self.assertEqual(len(build_failed), 1)

    def test_merged_finding_keeps_every_occurrence(self):
        build_failed = self.analysis.issues[0]
        self.assertEqual(build_failed.count, 3)
        self.assertEqual(build_failed.occurrences, [2, 4, 7])
        self.assertEqual(build_failed.first_line, 2)
        self.assertEqual(build_failed.last_line, 7)

    def test_labels_from_different_families_stay_separate(self):
        text = "ERROR connection refused to 10.0.0.1:5432\n" + ("INFO x\n" * 60) + "ERROR timed out after 1ms\n"
        labels = [issue.label for issue in analyze_text(text).issues]
        self.assertEqual(sorted(labels), ["Connection refused", "Timeout"])

    def test_unlabelled_groups_are_never_merged(self):
        text = "ERROR alpha subsystem unavailable\n" + ("INFO x\n" * 3) + "ERROR beta subsystem unavailable\n"
        self.assertEqual(len(analyze_text(text).issues), 2)

    def test_distant_groups_with_the_same_label_stay_separate(self):
        text = "ERROR npm ERR! code ELIFECYCLE\n" + ("INFO x\n" * 80) + "ERROR ELIFECYCLE Command failed\n"
        self.assertEqual(len(analyze_text(text).issues), 2)


if __name__ == "__main__":
    unittest.main()