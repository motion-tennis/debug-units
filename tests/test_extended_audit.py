"""Known-answer clock arithmetic and correlated pipeline failure fixtures."""

import copy
from decimal import Decimal
import unittest

from test_trace_audit import CHECKER, ROOT


class ClockAuditTests(unittest.TestCase):
    def setUp(self):
        self.records = CHECKER.read_records(ROOT / "examples/clock-trace.jsonl")
        self.config = self.records[0]["clock_audit"]
        self.maps = self.records[0]["clock_maps"]

    def report(self):
        return CHECKER.audit(self.records)

    def rejects(self, message):
        report = self.report()
        self.assertFalse(report["valid_trace"])
        self.assertTrue(any(message in error for error in report["errors"]), report["errors"])

    def test_two_mapping_bounds_add_before_capture_bounds(self):
        report = self.report()
        self.assertEqual(report["errors"], [])
        duration = report["clocks"]["durations"][0]
        self.assertEqual(Decimal(duration["center_us"]), 10000)
        self.assertEqual(Decimal(duration["uncertainty_us"]), 4020)
        self.assertEqual(Decimal(duration["lower_us"]), 5980)

    def test_signed_offsets_and_positive_negative_drift(self):
        for a, b, expected in (("1.0001", "-10000", 990100), ("0.9999", "10000", 1009900)):
            with self.subTest(a=a):
                self.maps[0].update(a=a, b=b)
                report = self.report()
                self.assertEqual(report["errors"], [])
                self.assertEqual(Decimal(report["clocks"]["conversions"][0]["mapped_us"]), expected)

    def test_growth_and_capture_scale(self):
        self.maps[0].update(a="1.1", anchor_us="0", growth_ppm="20")
        self.config["mapping_gate_us"] = "3000"
        row = self.report()["clocks"]["conversions"][0]
        self.assertEqual(Decimal(row["mapping_bound_us"]), 2020)
        self.assertEqual(Decimal(row["uncertainty_us"]), 2031)

    def test_overlap_does_not_invent_total_order(self):
        self.maps[1]["b"] = "0"
        row = self.report()["clocks"]["durations"][0]
        self.assertEqual(Decimal(row["lower_us"]), -4020)
        self.assertFalse(row["strictly_after"])

    def test_old_event_survives_later_invalidation(self):
        self.maps[0]["invalid_after_source_us"] = "1500000"
        self.assertEqual(self.report()["errors"], [])
        self.maps[0]["invalid_after_source_us"] = "1000000"
        self.rejects("invalidated at event time")

    def test_source_restart_and_reference_restart_fences(self):
        self.maps[0]["source"]["source_session_id"] = "new-boot"
        self.rejects("source session/clock mismatch")
        self.maps[0]["source"]["source_session_id"] = self.config["uses"][0]["event"]["source_session_id"]
        self.config["uses"][0]["reference"] = dict(self.config["uses"][0]["reference"], source_session_id="new-pi")
        self.rejects("wrong reference epoch")

    def test_expiry_and_capture_interval_edges(self):
        self.config["expiry_us"] = "1000000"
        self.rejects("expired at event time")
        self.config["expiry_us"] = "5000000"
        self.maps[0]["valid_until_us"] = "1000000"
        self.rejects("outside map validity")

    def test_unknown_negative_nonfinite_bounds(self):
        for value, message in ((None, "unknown mapping uncertainty"), ("-1", "invalid numeric"), ("NaN", "invalid numeric")):
            with self.subTest(value=value):
                self.maps[0]["bound_components_us"]["fit"] = value
                self.rejects(message)

    def test_gate_failure_does_not_produce_duration(self):
        self.maps[0]["growth_ppm"] = "20"
        self.maps[0]["anchor_us"] = "0"
        self.rejects("exceeds gate")
        report = self.report()
        self.assertEqual(report["clocks"]["conversions"][0]["status"], "uncertain")
        self.assertEqual(report["clocks"]["durations"], [])

    def test_missing_runtime_cannot_be_replaced_by_display(self):
        self.config["uses"][0]["kind"] = "display_mapping"
        self.rejects("cannot repair missing runtime")
        self.config["uses"].pop(0)
        self.rejects("missing expected runtime")

    def test_display_selection_and_overlap_rejection(self):
        self.config["expected_runtime_events"] = []
        use = self.config["uses"][0]
        use["kind"] = "display_mapping"
        self.rejects("missing or ambiguous display")
        self.config["display_selections"] = [{"source": self.maps[0]["source"], "reference": use["reference"],
                                              "mapping_id": "1", "from_us": "0", "until_us": "2000000"}]
        self.assertEqual(self.report()["errors"], [])
        self.config["display_selections"].append(copy.deepcopy(self.config["display_selections"][0]))
        self.rejects("overlapping display selection")

    def test_duplicate_map_or_assignment_rejected(self):
        self.maps.append(copy.deepcopy(self.maps[0]))
        self.rejects("duplicate immutable map")
        self.maps.pop()
        self.config["uses"].append(copy.deepcopy(self.config["uses"][0]))
        self.rejects("duplicate mapping-use")

    def test_pi_native_retains_capture_uncertainty(self):
        event = next(e for e in self.records[1:] if e["source_id"] == "physics-1")
        event["details"]["capture_uncertainty_us"] = "5"
        self.config["uses"].append({"kind": "pi_native", "event": {k: event[k] for k in ("source_id", "source_session_id", "event_seq")},
                                    "reference": {k: event[k] for k in ("source_id", "source_session_id", "clock_id")}})
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(Decimal(report["clocks"]["conversions"][-1]["uncertainty_us"]), 5)

    def test_no_duration_between_reference_epochs(self):
        self.maps[1]["reference"] = dict(self.maps[1]["reference"], source_session_id="pi-b")
        self.config["uses"][1]["reference"] = self.maps[1]["reference"]
        self.rejects("crosses reference epochs")

    def test_rejected_fit_event_does_not_replace_accepted_map(self):
        event = copy.deepcopy(self.records[-1])
        event.update(source_id="fit-review", source_session_id="fit-session", clock_id="pi-clock",
                     event_seq="0", event="clock_fit_rejected", transaction=None, details={"reason": "outlier"})
        self.records.append(event)
        self.assertEqual(self.report()["errors"], [])

    def test_raw_records_and_local_populations_unchanged(self):
        before = copy.deepcopy(self.records)
        report = self.report()
        self.assertEqual(self.records, before)
        del before[0]["clock_audit"]
        del before[0]["clock_maps"]
        core = CHECKER.audit(before)
        for field in ("response_us", "electrical_us", "outcomes", "started_transactions"):
            self.assertEqual(report[field], core[field])

    def test_empty_or_malformed_clock_profile_is_not_evidence(self):
        self.config["uses"] = []
        self.rejects("requires observed conversions")
        self.records[0]["clock_audit"] = []
        self.rejects("must be an object")

    def test_map_cannot_be_used_before_acceptance(self):
        self.maps[0]["accepted_reference_us"] = "1000000"
        self.rejects("predates acceptance")


class PipelineAuditTests(unittest.TestCase):
    def setUp(self):
        self.records = CHECKER.read_records(ROOT / "examples/pipeline-trace.jsonl")

    def event(self, name):
        return next(e for e in self.records if e.get("event") == name)

    def detail(self, name):
        return self.event(name)["details"]

    def report(self):
        return CHECKER.audit(self.records)

    def rejects(self, message):
        report = self.report()
        self.assertFalse(report["valid_trace"])
        self.assertTrue(any(message in e for e in report["errors"]), report["errors"])

    def renumber(self):
        groups = {}
        for event in self.records[1:]:
            groups.setdefault((event["source_id"], event["source_session_id"]), []).append(event)
        for group in groups.values():
            for index, event in enumerate(sorted(group, key=lambda e: int(e["mono_us"]))):
                event["event_seq"] = str(index)

    def test_success_and_reordered_file(self):
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["pipeline"]["complete_evidence"])
        self.records[1:] = reversed(self.records[1:])
        self.assertEqual(report, self.report())

    def test_missing_query_response_is_not_replaced_by_commit(self):
        self.records.remove(self.event("ball_query_receive"))
        self.rejects("missing ball_query_receive")

    def test_response_must_echo_ordered_query_keys(self):
        self.detail("ball_query_receive")["queries"][0]["query_id"] = "9"
        self.rejects("echo ordered queries")

    def test_old_writer_epoch_cannot_join(self):
        self.detail("state_commit_receive")["writer_epoch"] = "2"
        self.rejects("unknown batch/session/writer epoch")

    def test_stale_base_and_setup(self):
        update = self.detail("state_update_send")
        update["base_state_version"] = "9"
        self.rejects("stale candidate base")
        update["base_state_version"] = "10"
        update["roster_revision"] = "2"
        self.rejects("stale setup")

    def test_duplicate_retry_is_idempotent_but_conflict_fails(self):
        duplicate = copy.deepcopy(self.event("state_update_send"))
        duplicate["mono_us"] = "5100"
        self.records.append(duplicate)
        self.renumber()
        self.assertEqual(self.report()["errors"], [])
        duplicate["details"]["payload_sha256"] = "c" * 64
        self.rejects("conflicting duplicate")

    def test_missing_query_accounting(self):
        self.detail("state_update_send")["decisions"] = []
        self.rejects("disappeared")

    def test_technical_failure_is_not_normal_decision(self):
        self.detail("state_update_send")["decisions"][0]["outcome"] = "timeout"
        self.rejects("technical failure")

    def test_feedback_must_follow_commit_and_match_version(self):
        self.event("feedback_send")["mono_us"] = "5500"
        self.renumber()
        self.rejects("precedes commit acceptance")
        self.event("feedback_send")["mono_us"] = "7000"
        self.renumber()
        self.detail("feedback_send")["state_version"] = "12"
        self.rejects("feedback commit identity")

    def test_controller_response_cannot_change_commit_identity(self):
        self.detail("application_response")["batch_id"] = "99"
        self.rejects("controller response commit identity")

    def test_unknown_or_rejected_commit_cannot_publish(self):
        commit = self.detail("state_commit_receive")
        commit["accepted"] = None
        self.rejects("acceptance must be explicit")
        commit.update(accepted=False, reason="state_conflict")
        self.rejects("rejected commit was published")

    def test_honest_rejected_commit_and_query(self):
        self.detail("state_commit_receive").update(accepted=False, reason="state_conflict")
        self.records.remove(self.event("state_publication"))
        self.detail("feedback_send").update(committed=False, outcome="state_conflict")
        self.detail("application_response").update(committed=False, outcome="state_conflict")
        self.assertEqual(self.report()["errors"], [])
        self.records.remove(self.event("state_update_send"))
        self.records.remove(self.event("state_commit_receive"))
        self.detail("ball_query_receive").update(accepted=False, reason="state_conflict")
        self.renumber()
        self.assertEqual(self.report()["errors"], [])

    def test_rule_indices_and_causes(self):
        rule = {"event_index": "8", "kind": "contact", "has_cause": True, "cause_decision_index": "0"}
        self.detail("state_update_send")["rule_events"] = [rule]
        self.detail("state_publication")["rule_events"] = [copy.deepcopy(rule)]
        self.assertEqual(self.report()["errors"], [])
        rule["event_index"] = "0"
        self.rejects("8..23 namespace")
        rule["event_index"] = "8"
        rule["cause_decision_index"] = "1"
        self.rejects("unknown rule cause")

    def test_periodic_batch_has_query_response_and_no_fake_decision(self):
        for name in ("ball_query_send", "ball_query_receive"):
            self.detail(name)["queries"] = []
        for name in ("state_update_send", "state_publication"):
            self.detail(name)["decisions"] = []
            self.detail(name)["rule_events"] = [{"event_index": "8", "kind": "bounce", "has_cause": False}]
        self.records.remove(self.event("feedback_send"))
        self.event("application_response").update(event="input_dropped", details={"reason": "not admitted"})
        self.renumber()
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["pipeline"]["batches"][0]["decisions"], 0)

    def test_publication_must_preserve_atomic_events(self):
        self.detail("state_publication")["decisions"] = []
        self.rejects("publication changed candidate")

    def test_wrong_producer_and_absent_batch(self):
        self.event("state_commit_receive")["source_id"] = "other"
        self.rejects("producer binding mismatch")
        extra = copy.deepcopy(self.records[0]["pipeline_audit"]["batches"][0])
        extra["batch_id"] = "2"
        self.records[0]["pipeline_audit"]["batches"].append(extra)
        self.rejects("missing ball_query_send")

    def test_eight_queries_two_per_controller(self):
        template = copy.deepcopy(self.records)
        queries, decisions = [], []
        for index in range(8):
            tx = {"controller_id": "controller-" + str(index // 2 + 1), "session_id": "boot-a", "request_seq": str(index + 1)}
            queries.append({"query_id": str(index + 1), "transaction": tx})
            decisions.append({"query_id": str(index + 1), "transaction": tx, "event_index": str(index), "outcome": "miss"})
        self.records = [self.records[0]] + [e for e in template[1:] if e["event"] not in ("transaction_start", "application_response", "feedback_send")]
        for name in ("ball_query_send", "ball_query_receive"):
            self.detail(name)["queries"] = copy.deepcopy(queries)
        for name in ("state_update_send", "state_publication"):
            self.detail(name)["decisions"] = copy.deepcopy(decisions)
        for index, decision in enumerate(decisions):
            for name in ("transaction_start", "application_response", "feedback_send"):
                event = copy.deepcopy(next(e for e in template if e.get("event") == name))
                event["transaction"] = decision["transaction"]
                if name != "feedback_send":
                    event["source_id"] = decision["transaction"]["controller_id"]
                if name != "transaction_start":
                    event["details"]["event_index"] = str(index)
                self.records.append(event)
        self.renumber()
        self.assertEqual(self.report()["errors"], [])
        self.detail("ball_query_send")["queries"].append(copy.deepcopy(queries[0]))
        self.rejects("more than eight queries")
        self.detail("ball_query_send")["queries"].pop()
        items = self.detail("state_update_send")["decisions"]
        items[0], items[1] = items[1], items[0]
        items[0]["event_index"], items[1]["event_index"] = "0", "1"
        self.rejects("reorder the queried inputs")

    def test_unknown_technical_feedback_outcome_rejected(self):
        self.detail("feedback_send").update(committed=False, outcome="invented")
        self.rejects("unknown feedback outcome")

    def test_source_loss_keeps_partial_pipeline_report_incomplete(self):
        self.event("feedback_send")["event_seq"] = "5"
        report = self.report()
        self.assertFalse(report["valid_trace"])
        self.assertFalse(report["pipeline"]["complete_evidence"])

    def test_malformed_pipeline_manifest_is_rejected(self):
        self.records[0]["pipeline_audit"]["batches"] = [None]
        self.rejects("must be an object list")


if __name__ == "__main__":
    unittest.main()
