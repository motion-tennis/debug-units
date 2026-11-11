"""Known-answer and rejection cases for the offline marker overlay."""

import copy
import unittest

from test_trace_audit import CHECKER, ROOT


class MarkerAuditTests(unittest.TestCase):
    def setUp(self):
        self.records = CHECKER.read_records(ROOT / "examples" / "marker-trace.jsonl")
        self.header, self.marker, self.start, self.link, self.response = self.records

    def report(self):
        return CHECKER.audit(self.records)

    def rejects(self, message):
        report = self.report()
        self.assertFalse(report["valid_trace"])
        self.assertTrue(any(message in error for error in report["errors"]), report["errors"])

    def resequence(self):
        for index, event in enumerate(sorted(self.records[1:], key=lambda item: int(item["mono_us"]))):
            event["event_seq"] = str(index)

    def test_explicit_link_and_unchanged_core_populations(self):
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["markers"]["complete_evidence"])
        self.assertEqual(report["markers"]["target_outcomes"], {"miss": 1})
        core = copy.deepcopy(self.records)
        del core[0]["marker_audit"]
        core = [record for record in core if record.get("event") not in ("imu_threshold_trigger", "trigger_link")]
        for index, event in enumerate(core[1:]):
            event["event_seq"] = str(index)
        baseline = CHECKER.audit(core)
        for field in ("started_transactions", "received_application_results", "outcomes",
                      "response_us", "electrical_us", "per_controller", "censored_timeouts"):
            self.assertEqual(report[field], baseline[field])

    def test_file_order_does_not_change_result(self):
        original = self.report()
        self.records[1:] = reversed(self.records[1:])
        self.assertEqual(self.report(), original)

    def test_ambiguous_capture_is_honestly_unresolved(self):
        self.marker["details"]["capture_uncertainty_us"] = None
        self.marker["details"]["capture_uncertainty_reason"] = "shared interrupt attribution"
        self.link["transaction"] = None
        self.link["details"].update(link_status="unresolved", reason="unknown capture boundary")
        del self.link["details"]["target_sample_id"]
        del self.link["details"]["target_capture_us"]
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["markers"]["unresolved_markers"], 1)
        self.assertFalse(report["markers"]["complete_evidence"])

    def test_uncertain_resolved_link_is_rejected(self):
        self.marker["details"]["capture_uncertainty_us"] = "1500"
        self.rejects("uncertainty exceeds observation")

    def test_overlapping_capture_intervals_are_rejected(self):
        self.start["details"]["capture_uncertainty_us"] = "1000"
        self.rejects("ambiguous or earlier target")

    def test_wrong_session_and_unknown_targets(self):
        for field, value, message in (("session_id", "old-boot", "another controller/session"),
                                      ("request_seq", "99", "unknown or ambiguous target")):
            with self.subTest(field=field):
                original = self.link["transaction"][field]
                self.link["transaction"][field] = value
                self.rejects(message)
                self.link["transaction"][field] = original

    def test_unknown_marker_reference(self):
        self.link["details"]["trigger_id"] = "unknown"
        self.rejects("unknown trigger")

    def test_wrong_link_producer_session(self):
        self.link["details"]["trigger_session_id"] = "old-boot"
        self.rejects("source/session mismatch")

    def test_duplicate_and_conflicting_links(self):
        duplicate = copy.deepcopy(self.link)
        self.records.append(duplicate)
        self.resequence()
        self.rejects("exactly one link")
        duplicate["transaction"]["request_seq"] = "99"
        self.rejects("exactly one link")

    def test_multiple_markers_share_one_sample(self):
        marker, link = copy.deepcopy(self.marker), copy.deepcopy(self.link)
        marker["details"]["trigger_id"] = link["details"]["trigger_id"] = "2"
        marker["mono_us"] = "1200"
        self.records.extend([marker, link])
        self.header["marker_audit"]["sources"][0]["captured_markers"] = "2"
        self.resequence()
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["markers"]["linked_markers"], 2)
        self.assertEqual(report["started_transactions"], 1)
        self.assertEqual(report["response_us"]["count"], 1)

    def test_failed_targets_remain_selected(self):
        for event, time, outcome in (("input_dropped", "22000", "local_input_drop"),
                                     ("transaction_timeout", "52000", "local_timeout")):
            with self.subTest(event=event):
                self.response["event"], self.response["mono_us"] = event, time
                report = self.report()
                self.assertEqual(report["errors"], [])
                self.assertEqual(report["markers"]["target_outcomes"], {outcome: 1})
                self.assertEqual(report["response_us"]["count"], 0)

    def test_cannot_relink_to_later_success(self):
        earlier = copy.deepcopy(self.start)
        earlier["transaction"]["request_seq"] = "0"
        earlier["details"]["imu_sample_ids"] = ["100"]
        earlier["mono_us"] = "1500"
        dropped = copy.deepcopy(earlier)
        dropped.update(event="input_dropped", mono_us="1600", details={"reason": "queue full"})
        self.records.extend([earlier, dropped])
        self.resequence()
        self.rejects("not provably the first capture")

    def test_missing_link_and_source_loss_are_visible(self):
        self.records.remove(self.link)
        report = self.report()
        self.assertEqual(report["markers"]["missing_links"], 1)
        self.assertGreater(report["source_sequence_gaps"], 0)
        self.assertFalse(report["markers"]["complete_evidence"])

    def test_loss_prevents_first_capture_claim(self):
        self.response["event_seq"] = "4"
        self.rejects("trace loss prevents")

    def test_absent_registered_source_is_detected(self):
        source = copy.deepcopy(self.header["marker_audit"]["sources"][0])
        source["controller_id"] = "controller-absent"
        self.header["marker_audit"]["sources"].append(source)
        self.rejects("missing source")

    def test_missing_terminal_is_not_a_successful_target(self):
        self.records.remove(self.response)
        report = self.report()
        self.assertFalse(report["valid_trace"])
        self.assertEqual(report["markers"]["target_outcomes"], {"incomplete": 1})

    def test_configuration_clock_sample_and_association_fences(self):
        mutations = [(self.marker["details"], "trigger_config_id", "unknown", "unknown trigger configuration"),
                     (self.link, "clock_id", "other", "marker clock mismatch"),
                     (self.link["details"], "target_sample_id", "999", "target sample"),
                     (self.link["details"], "target_capture_us", "2001", "capture provenance"),
                     (self.start["details"], "association_id", "repaired", "changed association"),
                     (self.start["details"], "calibration_id", "new", "changed calibration")]
        for obj, field, value, message in mutations:
            with self.subTest(field=field):
                old = obj[field]
                obj[field] = value
                self.rejects(message)
                obj[field] = old

    def test_manifest_and_capture_counter_required(self):
        self.header["marker_audit"]["sources"][0]["captured_markers"] = "2"
        self.rejects("count mismatch")
        del self.header["marker_audit"]
        self.rejects("require marker_audit")

    def test_observation_cutoff_is_not_a_timeout(self):
        self.header["marker_audit"]["sources"][0]["observation_cutoff_us"] = "2050"
        self.rejects("outside observation window")
        self.assertEqual(self.report()["censored_timeouts"], 0)

    def test_duplicate_marker_identity(self):
        self.records.append(copy.deepcopy(self.marker))
        self.resequence()
        self.rejects("duplicate trigger identity")

    def test_malformed_marker_metadata_does_not_crash(self):
        for value in (None, [], "invalid", {"sources": []}):
            with self.subTest(value=value):
                self.header["marker_audit"] = value
                self.assertFalse(self.report()["valid_trace"])

    def test_unknown_capture_uncertainty_cannot_resolve(self):
        self.start["details"]["capture_uncertainty_us"] = None
        self.start["details"]["capture_uncertainty_reason"] = "not characterized"
        self.rejects("unknown capture timing")

    def test_unresolved_link_cannot_invent_target(self):
        self.link["details"].update(link_status="unresolved", reason="ambiguous")
        self.rejects("invented target")

    def test_reboot_can_reuse_marker_counter_without_cross_session_join(self):
        reboot = copy.deepcopy(self.records[1:])
        for event in reboot:
            event["source_session_id"] = "boot-b"
            if event["transaction"] is not None:
                event["transaction"]["session_id"] = "boot-b"
            if event["event"] == "trigger_link":
                event["details"]["trigger_session_id"] = "boot-b"
        source = copy.deepcopy(self.header["marker_audit"]["sources"][0])
        source["session_id"] = "boot-b"
        self.header["marker_audit"]["sources"].append(source)
        self.records.extend(reboot)
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["markers"]["linked_markers"], 2)

    def test_log_drop_prevents_complete_marker_claim(self):
        loss = copy.deepcopy(self.response)
        loss.update(event="log_drop", transaction=None, event_seq="4", details={"count": "1"})
        self.records.append(loss)
        self.rejects("trace loss prevents")


if __name__ == "__main__":
    unittest.main()
