#!/usr/bin/env python3
"""Audit normalized Motion Tennis trace-v1 JSONL without third-party packages."""

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


U64_MAX = (1 << 64) - 1
DECIMAL = re.compile(r"0|[1-9][0-9]*")
CONTROLLER_EVENTS = {
    "transaction_start", "application_response", "electrical_feedback",
    "transaction_timeout", "input_dropped", "feedback_suppressed",
}
TERMINALS = {"application_response", "transaction_timeout", "input_dropped"}
OUTCOMES = {
    "hit", "miss", "invalid_input", "tracking_unavailable", "stale_input",
    "state_conflict", "timeout", "overloaded", "internal_error",
}


def uint(value):
    """Return a canonical unsigned 64-bit decimal string as an integer."""
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError("expected a canonical unsigned decimal string")
    number = int(value)
    if number > U64_MAX:
        raise ValueError("value exceeds unsigned 64-bit range")
    return number


def label(value):
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 128


def reject_constant(value):
    raise ValueError("non-finite JSON value: " + value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_records(path):
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(
                    line, parse_constant=reject_constant,
                    object_pairs_hook=unique_object,
                ))
            except ValueError as exc:
                raise ValueError(f"line {line_number}: {exc}") from exc
    return records


def distribution(values, target):
    ordered = sorted(values)
    result = {"count": len(ordered), "target_us": target}
    if not ordered:
        return dict(result, median_us=None, p95_us=None, p99_us=None,
                    observed_max_us=None, target_exceedances=0,
                    p99_meets_target=None)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    p99 = ordered[math.ceil(0.99 * len(ordered)) - 1]
    return dict(result, median_us=statistics.median(ordered), p95_us=p95,
                p99_us=p99, observed_max_us=ordered[-1],
                target_exceedances=sum(value > target for value in ordered),
                p99_meets_target=p99 <= target)


def audit(records):
    """Check trace integrity and compute only same-controller clock intervals."""
    errors = []
    if not records or not isinstance(records[0], dict):
        return {"errors": ["first record must be a run object"]}
    header = records[0]
    if header.get("record_type") != "run" or header.get("trace_version") != "1":
        errors.append("first record must identify trace_version 1 and record_type run")
    if not label(header.get("run_id")) or not isinstance(header.get("synthetic"), bool):
        errors.append("run header needs a run_id and a boolean synthetic flag")
    limits = {}
    for field in ("response_deadline_us", "electrical_deadline_us", "transaction_timeout_us"):
        try:
            limits[field] = uint(header.get(field))
            if limits[field] == 0:
                errors.append(field + " must be positive")
        except ValueError as exc:
            errors.append(field + ": " + str(exc))
    if errors:
        return {"errors": errors}
    if not (limits["response_deadline_us"] <= limits["electrical_deadline_us"]
            <= limits["transaction_timeout_us"]):
        return {"errors": ["response target <= electrical target <= expiry is required"]}

    transactions = defaultdict(list)
    sources = defaultdict(list)
    event_counts = Counter()
    reported_log_drops = 0
    for index, original in enumerate(records[1:], 2):
        prefix = f"record {index}: "
        if not isinstance(original, dict):
            errors.append(prefix + "event must be an object")
            continue
        record = dict(original)
        valid = True
        if record.get("record_type") != "event" or record.get("run_id") != header["run_id"]:
            errors.append(prefix + "wrong record type or run ID")
            valid = False
        for field in ("source_id", "source_session_id", "clock_id", "event"):
            if not label(record.get(field)):
                errors.append(prefix + field + " must be a nonempty identifier")
                valid = False
        for field in ("event_seq", "mono_us"):
            try:
                record["_" + field] = uint(record.get(field))
            except ValueError as exc:
                errors.append(prefix + field + ": " + str(exc))
                valid = False
        if not isinstance(record.get("details"), dict):
            errors.append(prefix + "details must be an object")
            valid = False
        transaction = record.get("transaction")
        key = None
        if transaction is not None:
            try:
                if not isinstance(transaction, dict):
                    raise ValueError("transaction must be an object or null")
                if not label(transaction.get("controller_id")) or not label(transaction.get("session_id")):
                    raise ValueError("invalid controller or controller session ID")
                uint(transaction.get("request_seq"))
                key = (transaction["controller_id"], transaction["session_id"], transaction["request_seq"])
            except ValueError as exc:
                errors.append(prefix + str(exc))
                valid = False
        elif "transaction" not in record or record.get("event") in CONTROLLER_EVENTS:
            errors.append(prefix + "controller events need a transaction; other events need explicit null")
            valid = False
        if not valid:
            continue
        if record["event"] in CONTROLLER_EVENTS and (record["source_id"], record["source_session_id"]) != key[:2]:
            errors.append(prefix + "controller event source does not match its transaction")
            continue
        event_counts[record["event"]] += 1
        sources[(record["source_id"], record["source_session_id"])].append(record)
        if key is not None:
            transactions[key].append(record)
        if record["event"] == "log_drop":
            try:
                reported_log_drops += uint(record["details"].get("count"))
            except ValueError as exc:
                errors.append(prefix + "log_drop count: " + str(exc))

    sequence_gaps = 0
    for source, events in sources.items():
        sequences = [event["_event_seq"] for event in events]
        if len(sequences) != len(set(sequences)):
            errors.append(str(source) + ": duplicate source event sequence")
        ordered = sorted(set(sequences))
        sequence_gaps += ordered[-1] + 1 - len(ordered)
        previous = {}
        for event in sorted(events, key=lambda item: item["_event_seq"]):
            clock = event["clock_id"]
            if clock in previous and event["_mono_us"] < previous[clock]:
                errors.append(str(source) + ": monotonic time regressed within one source clock")
            previous[clock] = event["_mono_us"]

    outcomes = Counter()
    responses = []
    electrical = []
    response_by_outcome = defaultdict(list)
    response_by_controller = defaultdict(list)
    electrical_by_controller = defaultdict(list)
    controller_starts = Counter()
    gameplay_responses = []
    started = censored = dropped = pending = eligible = absent = suppressed = 0
    for key, events in sorted(transactions.items()):
        description = "/".join(key)
        local = [event for event in events if event["event"] in CONTROLLER_EVENTS]
        if not local:
            continue
        starts = [event for event in local if event["event"] == "transaction_start"]
        if len(starts) != 1:
            errors.append(description + ": expected exactly one transaction_start")
            continue
        started += 1
        controller_starts[key[0]] += 1
        start = starts[0]
        local_valid = True
        for event in local:
            if event["clock_id"] != start["clock_id"]:
                errors.append(description + ": controller timing crosses clock domains")
                local_valid = False
            if event["_mono_us"] < start["_mono_us"]:
                errors.append(description + ": event precedes transaction start")
                local_valid = False
        if not local_valid:
            continue
        terminals = [event for event in local if event["event"] in TERMINALS]
        if not terminals:
            pending += 1
            errors.append(description + ": no terminal outcome at trace cutoff")
            continue
        if len(terminals) != 1:
            errors.append(description + ": more than one terminal outcome")
            continue
        terminal = terminals[0]
        elapsed = terminal["_mono_us"] - start["_mono_us"]
        actuations = [event for event in local if event["event"] == "electrical_feedback"]
        suppressions = [event for event in local if event["event"] == "feedback_suppressed"]
        if terminal["event"] == "transaction_timeout":
            censored += 1
            outcomes["local_timeout"] += 1
            if elapsed < limits["transaction_timeout_us"]:
                errors.append(description + ": timeout occurred before declared expiry")
            if actuations or suppressions:
                errors.append(description + ": local timeout cannot have gameplay electrical feedback")
            continue
        if terminal["event"] == "input_dropped":
            dropped += 1
            outcomes["local_input_drop"] += 1
            if actuations or suppressions:
                errors.append(description + ": dropped input cannot have gameplay electrical feedback")
            continue

        detail = terminal["details"]
        outcome = detail.get("outcome")
        output = detail.get("electrical_output")
        if outcome not in OUTCOMES:
            errors.append(description + ": unknown application outcome")
            continue
        if "electrical_output" not in detail or output not in (None, "led", "motor"):
            errors.append(description + ": electrical_output must explicitly be led, motor or null")
            continue
        if elapsed >= limits["transaction_timeout_us"]:
            errors.append(description + ": response at or after expiry must be discarded, not completed")
            continue
        outcomes[outcome] += 1
        responses.append(elapsed)
        response_by_outcome[outcome].append(elapsed)
        response_by_controller[key[0]].append(elapsed)
        if outcome in ("hit", "miss"):
            gameplay_responses.append(elapsed)
        if output is None:
            absent += 1
            if actuations or suppressions:
                errors.append(description + ": ineligible response cannot have a gameplay cue")
            continue
        eligible += 1
        cue_id = detail.get("cue_id")
        if not label(cue_id):
            errors.append(description + ": eligible cue needs a cue_id")
        if len(actuations) + len(suppressions) != 1:
            errors.append(description + ": eligible cue needs exactly one actuation or suppression record")
            continue
        cue = (actuations + suppressions)[0]
        if cue["details"].get("output") != output or cue["details"].get("cue_id") != cue_id:
            errors.append(description + ": output or cue identity mismatch")
            continue
        if cue["_mono_us"] < terminal["_mono_us"]:
            errors.append(description + ": cue precedes valid application response")
            continue
        if suppressions:
            suppressed += 1
            continue
        electrical_elapsed = cue["_mono_us"] - start["_mono_us"]
        if electrical_elapsed >= limits["transaction_timeout_us"]:
            errors.append(description + ": expired electrical cue must be suppressed")
            continue
        electrical.append(electrical_elapsed)
        electrical_by_controller[key[0]].append(electrical_elapsed)

    if not started:
        errors.append("trace contains no started measurement transactions")
    if sequence_gaps or reported_log_drops:
        errors.append("trace evidence is incomplete: source sequence gaps or reported log loss")
    return {
        "run_id": header["run_id"], "synthetic": header["synthetic"],
        "valid_trace": not errors, "started_transactions": started,
        "received_application_results": len(responses), "censored_timeouts": censored,
        "locally_dropped_inputs": dropped, "pending_at_cutoff": pending,
        "outcomes": dict(sorted(outcomes.items())),
        "eligible_electrical_cues": eligible, "ineligible_electrical_cues": absent,
        "suppressed_electrical_cues": suppressed,
        "response_us": distribution(responses, limits["response_deadline_us"]),
        "electrical_us": distribution(electrical, limits["electrical_deadline_us"]),
        "gameplay_response_us": distribution(gameplay_responses, limits["response_deadline_us"]),
        "response_by_outcome_us": {
            key: distribution(values, limits["response_deadline_us"])
            for key, values in sorted(response_by_outcome.items())
        },
        "per_controller": {
            controller: {
                "started_transactions": count,
                "response_us": distribution(response_by_controller[controller], limits["response_deadline_us"]),
                "electrical_us": distribution(electrical_by_controller[controller], limits["electrical_deadline_us"]),
            }
            for controller, count in sorted(controller_starts.items())
        },
        "event_counts": dict(sorted(event_counts.items())),
        "source_sequence_gaps": sequence_gaps, "reported_log_drops": reported_log_drops,
        "percentile_method": "median; nearest-rank p95 and p99",
        "limits": "Local trace audit only; no runtime, wire, physics, clock-mapping or hardware validation.",
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Normalized trace-v1 JSONL file")
    args = parser.parse_args()
    try:
        result = audit(read_records(args.trace))
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"errors": [str(exc)]}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
