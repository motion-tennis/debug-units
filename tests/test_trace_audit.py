"""Exercise measurement-integrity failures using the synthetic end-to-end fixture."""

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_trace", ROOT / "scripts" / "check_trace.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class TraceAuditTests(unittest.TestCase):
    def setUp(self):
        self.records = CHECKER.read_records(ROOT / "examples" / "synthetic-trace.jsonl")

    def test_synthetic_accounting_includes_errors_timeouts_and_drops(self):
        result = CHECKER.audit(self.records)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["started_transactions"], 5)
        self.assertEqual(result["received_application_results"], 3)
        self.assertEqual(result["censored_timeouts"], 1)
        self.assertEqual(result["locally_dropped_inputs"], 1)
        self.assertEqual(result["response_us"]["median_us"], 20000)
        self.assertEqual(result["response_us"]["p99_us"], 32000)
        self.assertEqual(result["response_us"]["target_exceedances"], 1)
        self.assertEqual(result["ineligible_electrical_cues"], 1)

    def test_mixed_clock_subtraction_is_rejected(self):
        response = next(record for record in self.records if record.get("event") == "application_response")
        response["clock_id"] = "different-clock"
        self.assertTrue(any("crosses clock domains" in error for error in CHECKER.audit(self.records)["errors"]))

    def test_duplicate_actuation_is_rejected(self):
        actuation = copy.deepcopy(next(record for record in self.records if record.get("event") == "electrical_feedback"))
        actuation["event_seq"] = "3"
        actuation["mono_us"] = "1022000"
        self.records.append(actuation)
        self.assertTrue(any("exactly one actuation" in error for error in CHECKER.audit(self.records)["errors"]))

    def test_missing_timeout_does_not_become_success(self):
        self.records = [record for record in self.records if record.get("event") != "transaction_timeout"]
        result = CHECKER.audit(self.records)
        self.assertEqual(result["pending_at_cutoff"], 1)
        self.assertTrue(any("no terminal outcome" in error for error in result["errors"]))

    def test_expired_response_cannot_be_counted_as_completion(self):
        for record in self.records:
            if record.get("source_id") == "controller-1":
                if record.get("event") == "application_response":
                    record["mono_us"] = "1050000"
                if record.get("event") == "electrical_feedback":
                    record["mono_us"] = "1051000"
        self.assertTrue(any("at or after expiry" in error for error in CHECKER.audit(self.records)["errors"]))

    def test_missing_trace_records_are_reported(self):
        record = next(record for record in self.records if record.get("source_id") == "physics-1")
        self.records.remove(record)
        result = CHECKER.audit(self.records)
        self.assertGreater(result["source_sequence_gaps"], 0)
        self.assertFalse(result["valid_trace"])

    def test_unmatched_old_response_is_diagnostic_not_a_new_transaction(self):
        discarded = copy.deepcopy(next(record for record in self.records if record.get("event") == "response_discarded"))
        discarded["event_seq"] = "4"
        discarded["mono_us"] = "1061000"
        discarded["transaction"]["session_id"] = "older-controller-session"
        self.records.append(discarded)
        result = CHECKER.audit(self.records)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["started_transactions"], 5)
        self.assertEqual(result["event_counts"]["response_discarded"], 2)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.jsonl"
            path.write_text('{"record_type":"run","record_type":"event"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                CHECKER.read_records(path)

    def test_empty_run_is_not_evidence(self):
        self.assertTrue(any("no started" in error for error in CHECKER.audit(self.records[:1])["errors"]))


if __name__ == "__main__":
    unittest.main()
