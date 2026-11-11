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

from audit_extensions import audit_clocks, audit_pipeline


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


def audit_markers(header, sources, transactions, loss):
    """Validate an explicit, bounded offline marker overlay; never infer links."""
    errors = []
    markers = defaultdict(list)
    links = defaultdict(list)
    invalid = set()
    registry = {}
    config = header.get("marker_audit")
    events = [event for group in sources.values() for event in group
              if event["event"] in ("imu_threshold_trigger", "trigger_link")]
    if config is None and not events:
        return None, errors
    result = {"captured_markers": 0, "linked_markers": 0,
              "unresolved_markers": 0, "missing_links": 0,
              "target_outcomes": {}, "complete_evidence": False}

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def interval(event):
        detail = event["details"]
        uncertainty = detail.get("capture_uncertainty_us")
        if uncertainty is None:
            require(label(detail.get("capture_uncertainty_reason")),
                    "unknown capture uncertainty needs a reason")
            return None
        bound = uint(uncertainty)
        return event["_mono_us"] - bound, event["_mono_us"] + bound

    try:
        require(isinstance(config, dict), "marker events require marker_audit metadata")
        require(config.get("link_rule") == "first_capture_at_or_after_trigger",
                "unsupported marker link rule")
        require(config.get("sample_capture_boundary") == "transaction_start",
                "marker audit requires declared transaction_start capture boundary")
        entries = config.get("sources")
        require(isinstance(entries, list) and bool(entries), "marker sources must be a nonempty list")
        for entry in entries:
            require(isinstance(entry, dict), "marker source must be an object")
            require(all(label(entry.get(name)) for name in
                        ("controller_id", "session_id", "clock_id")), "invalid marker source identity")
            key = (entry["controller_id"], entry["session_id"])
            require(key not in registry, "duplicate marker source registration")
            begin, cutoff = uint(entry.get("observation_start_us")), uint(entry.get("observation_cutoff_us"))
            require(begin <= cutoff, "marker observation window is reversed")
            uint(entry.get("captured_markers"))
            configs = entry.get("trigger_config_ids")
            require(isinstance(configs, list) and bool(configs) and all(label(value) for value in configs),
                    "trigger_config_ids must name known configurations")
            registry[key] = entry
    except ValueError as exc:
        errors.append("markers: " + str(exc))
        return result, errors

    for event in events:
        key = None
        try:
            detail = event["details"]
            source = (event["source_id"], event["source_session_id"])
            require(source in registry, "unknown marker source/session")
            entry = registry[source]
            require(event["clock_id"] == entry["clock_id"], "marker clock mismatch")
            require(uint(entry["observation_start_us"]) <= event["_mono_us"] <=
                    uint(entry["observation_cutoff_us"]), "marker event outside observation window")
            require(label(detail.get("trigger_id")), "invalid trigger_id")
            key = source + (detail["trigger_id"],)
            if event["event"] == "imu_threshold_trigger":
                markers[key].append(event)
                require(event["transaction"] is None, "trigger must not create a transaction")
                require(detail.get("trigger_config_id") in entry["trigger_config_ids"],
                        "unknown trigger configuration")
                require(detail.get("trigger_boundary") in ("hardware_irq_edge", "isr_entry"),
                        "unsupported trigger capture boundary")
                interval(event)
                for field, expected in (("trigger_controller_id", source[0]), ("trigger_session_id", source[1])):
                    require(field not in detail or detail[field] == expected, "trigger reference identity mismatch")
            else:
                require((detail.get("trigger_controller_id"), detail.get("trigger_session_id")) == source,
                        "link marker source/session mismatch")
                links[key].append(event)
                require(detail.get("link_rule") == config["link_rule"], "link rule differs from manifest")
                require(detail.get("link_status") in ("resolved", "unresolved"), "unknown link status")
        except (ValueError, TypeError) as exc:
            if key is not None:
                invalid.add(key)
            errors.append("markers: " + str(exc))

    result["captured_markers"] = sum(len(group) for group in markers.values())
    outcomes = Counter()
    for source, entry in registry.items():
        count = sum(len(group) for key, group in markers.items() if key[:2] == source)
        if source not in sources or count != uint(entry["captured_markers"]):
            errors.append("markers: missing source or captured marker count mismatch: " + "/".join(source))
    for key in links.keys() - markers.keys():
        errors.append("markers: link references an unknown trigger: " + "/".join(key))
    for key, captures in markers.items():
        prefix = "marker " + "/".join(key) + ": "
        try:
            require(key not in invalid, "invalid marker or link metadata")
            require(len(captures) == 1, "duplicate trigger identity")
            associations = links.get(key, [])
            if not associations:
                result["missing_links"] += 1
            require(len(associations) == 1, "expected exactly one link; missing, duplicate or conflicting links")
            marker, link = captures[0], associations[0]
            detail = link["details"]
            require(link["_mono_us"] >= marker["_mono_us"], "link precedes trigger")
            if detail.get("link_status") == "unresolved":
                require(link["transaction"] is None and "target_sample_id" not in detail
                        and "target_capture_us" not in detail, "unresolved link contains an invented target")
                require(label(detail.get("reason")), "unresolved link needs a reason")
                result["unresolved_markers"] += 1
                continue
            require(detail.get("link_status") == "resolved", "invalid link status")
            target = link["transaction"]
            require(isinstance(target, dict), "resolved link needs a target transaction")
            target_key = (target["controller_id"], target["session_id"], target["request_seq"])
            require(target_key[:2] == key[:2], "target belongs to another controller/session")
            starts = [event for event in transactions.get(target_key, []) if event["event"] == "transaction_start"]
            require(len(starts) == 1, "unknown or ambiguous target transaction")
            start = starts[0]
            require(start["clock_id"] == marker["clock_id"], "target clock differs from trigger")
            samples = start["details"].get("imu_sample_ids")
            require(isinstance(samples, list) and len(samples) == 1 and label(samples[0])
                    and detail.get("target_sample_id") == samples[0], "unknown or ambiguous target sample")
            uint(samples[0])
            require(uint(detail.get("target_capture_us")) == start["_mono_us"], "target capture provenance mismatch")
            require(link["_mono_us"] >= start["_mono_us"], "link precedes target capture")
            for field in ("association_id", "calibration_id"):
                require(label(marker["details"].get(field)) and
                        marker["details"][field] == start["details"].get(field),
                        "missing or changed " + field)
            trigger_range, target_range = interval(marker), interval(start)
            require(trigger_range is not None and target_range is not None,
                    "unknown capture timing must remain unresolved")
            require(trigger_range[0] >= uint(registry[key[:2]]["observation_start_us"]),
                    "trigger uncertainty exceeds observation coverage")
            require(target_range[0] >= trigger_range[1], "ambiguous or earlier target capture")
            require(target_range[1] <= uint(registry[key[:2]]["observation_cutoff_us"]),
                    "target capture exceeds observation coverage")
            candidates = [event for event in sources[key[:2]] if event["event"] == "transaction_start"
                          and event is not start]
            for candidate in candidates:
                require(detail["target_sample_id"] not in candidate["details"].get("imu_sample_ids", []),
                        "target sample identity is reused")
                require(candidate["clock_id"] == marker["clock_id"], "sample coverage crosses clocks")
                candidate_range = interval(candidate)
                require(candidate_range is not None, "unknown sample capture timing must remain unresolved")
                require(candidate_range[1] < trigger_range[0] or candidate_range[0] > target_range[1],
                        "target is not provably the first capture; earlier or ambiguous sample")
            require(not loss, "trace loss prevents complete first-capture proof")
            terminals = [event for event in transactions[target_key] if event["event"] in TERMINALS]
            outcome = "incomplete"
            if len(terminals) == 1:
                terminal = terminals[0]
                outcome = {"transaction_timeout": "local_timeout", "input_dropped": "local_input_drop"}.get(
                    terminal["event"], terminal["details"].get("outcome", "invalid"))
            outcomes[outcome] += 1
            result["linked_markers"] += 1
        except (ValueError, TypeError) as exc:
            errors.append(prefix + str(exc))
    result["target_outcomes"] = dict(sorted(outcomes.items()))
    result["complete_evidence"] = (not errors and not loss and result["unresolved_markers"] == 0
                                   and "incomplete" not in outcomes)
    return result, errors


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
    marker_report, marker_errors = audit_markers(
        header, sources, transactions, bool(sequence_gaps or reported_log_drops))
    errors.extend(marker_errors)
    valid_events = [event for group in sources.values() for event in group]
    clock_report, clock_errors = audit_clocks(header, valid_events)
    pipeline_report, pipeline_errors = audit_pipeline(header, valid_events)
    errors.extend(clock_errors)
    errors.extend(pipeline_errors)
    for extension_report in (clock_report, pipeline_report):
        if extension_report is not None and errors:
            extension_report["complete_evidence"] = False
    if marker_report is not None and errors:
        marker_report["complete_evidence"] = False
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
        "markers": marker_report,
        "clocks": clock_report, "pipeline": pipeline_report,
        "limits": "Offline declared trace conformance only; no runtime, wire decoding, clock fitting, physics or hardware validation.",
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
