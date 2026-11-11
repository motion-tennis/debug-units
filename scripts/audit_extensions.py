"""Bounded offline clock and pipeline evidence checks; no runtime authority."""

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
import json
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 128, "invalid identifier")
    return value


def unsigned(value):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value) is not None,
            "expected unsigned decimal string")
    require(int(value) < 2**64, "unsigned value exceeds 64 bits")
    return int(value)


def number(value, nonnegative=False):
    require(isinstance(value, str) and len(value) <= 32, "expected bounded decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    require(result.is_finite() and (not nonnegative or result >= 0), "invalid numeric bound/coefficient")
    require(result == 0 or -30 <= result.adjusted() <= 30, "decimal magnitude outside offline profile")
    return result


def binding(value):
    require(isinstance(value, dict), "binding must be an object")
    return tuple(identifier(value.get(name)) for name in ("source_id", "source_session_id", "clock_id"))


def event_key(value):
    require(isinstance(value, dict), "event reference must be an object")
    return (identifier(value.get("source_id")), identifier(value.get("source_session_id")),
            str(unsigned(value.get("event_seq"))))


def transaction_key(value):
    require(isinstance(value, dict), "transaction must be an object")
    return (identifier(value.get("controller_id")), identifier(value.get("session_id")),
            str(unsigned(value.get("request_seq"))))


def objects(value, name):
    require(isinstance(value, list) and all(isinstance(item, dict) for item in value), name + " must be an object list")
    return value


def text_decimal(value):
    return format(value, "f")


def audit_clocks(header, events):
    with localcontext() as context:
        context.prec = 80
        return _audit_clocks(header, events)


def _audit_clocks(header, events):
    """Consume immutable Pi maps; retain unresolved mappings and uncertainty."""
    config = header.get("clock_audit")
    if config is None:
        return None, []
    errors, converted, durations = [], [], []
    maps, indexed, selections = {}, {}, []
    result = {"conversions": converted, "durations": durations, "complete_evidence": False}
    try:
        require(isinstance(config, dict), "clock_audit must be an object")
        gate = number(config.get("mapping_gate_us"), True)
        expiry = unsigned(config.get("expiry_us"))
        require(gate > 0 and expiry > 0, "clock gates must be positive")
        for event in events:
            key = event_key(event)
            require(key not in indexed, "ambiguous duplicate source event")
            indexed[key] = event
        for record in objects(header.get("clock_maps"), "clock_maps"):
            ref = binding(record.get("reference"))
            source = binding(record.get("source"))
            key = (ref, identifier(record.get("mapping_id")))
            require(key not in maps, "duplicate immutable map identity")
            require(record.get("units") == "microseconds", "unsupported map units")
            a, b = number(record.get("a")), number(record.get("b"))
            require(a > 0, "map scale must be positive")
            begin, end = unsigned(record.get("valid_from_us")), unsigned(record.get("valid_until_us"))
            anchor = unsigned(record.get("anchor_us"))
            require(begin <= anchor <= end, "invalid map interval/anchor")
            accepted, last_good = unsigned(record.get("accepted_reference_us")), unsigned(record.get("last_good_reference_us"))
            require(last_good <= accepted, "last good exchange follows map acceptance")
            identifier(record.get("method_revision"))
            require(record.get("status") == "valid", "registry requires accepted valid maps")
            components = record.get("bound_components_us")
            require(isinstance(components, dict) and bool(components), "map bound components are required")
            bounds = []
            for name, value in components.items():
                identifier(name)
                bounds.append(None if value is None else number(value, True))
            growth = record.get("growth_ppm")
            growth = None if growth is None else number(growth, True)
            invalid_after = record.get("invalid_after_source_us")
            if invalid_after is not None:
                invalid_after = unsigned(invalid_after)
            maps[key] = (record, source, a, b, begin, end, anchor, accepted, last_good,
                         bounds, growth, invalid_after)
        for entry in objects(config.get("display_selections", []), "display_selections"):
            source, ref = binding(entry.get("source")), binding(entry.get("reference"))
            begin, end = unsigned(entry.get("from_us")), unsigned(entry.get("until_us"))
            require(begin < end, "empty display selection")
            key = (ref, identifier(entry.get("mapping_id")))
            require(key in maps and maps[key][1] == source, "display selection has no matching map")
            for old_source, old_begin, old_end, _ in selections:
                require(old_source != source or end <= old_begin or begin >= old_end,
                        "overlapping display selection rewrites history")
            selections.append((source, begin, end, key))
        uses = objects(config.get("uses"), "clock uses")
        require(bool(uses), "clock audit requires observed conversions")
        required = {event_key(value) for value in objects(config.get("expected_runtime_events", []), "expected runtime events")}
        seen, valid = set(), {}
        for use in uses:
            row = {"event": use.get("event"), "status": "invalid"}
            converted.append(row)
            try:
                key = event_key(use.get("event"))
                require(key not in seen, "duplicate mapping-use assignment")
                seen.add(key)
                require(key in indexed, "mapping use references missing event")
                event = indexed[key]
                source = binding(event)
                raw = unsigned(event["mono_us"])
                capture = number(event["details"].get("capture_uncertainty_us"), True)
                ref = binding(use.get("reference"))
                kind = use.get("kind")
                require(kind in ("runtime_mapping_use", "display_mapping", "pi_native"), "unknown conversion kind")
                require(key not in required or kind == "runtime_mapping_use", "display mapping cannot repair missing runtime use")
                if kind == "pi_native":
                    require(source == ref, "Pi identity conversion crosses reference epochs")
                    center, uncertainty, mapping_bound = Decimal(raw), capture, Decimal(0)
                    require("mapping_id" not in use, "Pi-native conversion must not name a fitted map")
                else:
                    map_key = (ref, identifier(use.get("mapping_id")))
                    require(map_key in maps, "missing map or wrong reference epoch")
                    record, expected_source, a, b, begin, end, anchor, accepted, last_good, bounds, growth, invalid_after = maps[map_key]
                    require(source == expected_source, "map source session/clock mismatch")
                    require(begin <= Decimal(raw) - capture and Decimal(raw) + capture <= end, "event outside map validity")
                    require(invalid_after is None or Decimal(raw) + capture < invalid_after, "map invalidated at event time")
                    require(all(value is not None for value in bounds) and growth is not None, "unknown mapping uncertainty")
                    with localcontext() as context:
                        context.prec = 80
                        center = a * raw + b
                        mapping_bound = sum(bounds) + growth * abs(Decimal(raw) - anchor) / Decimal(1000000)
                        uncertainty = mapping_bound + abs(a) * capture
                    require(center - uncertainty >= accepted, "map use predates acceptance")
                    require(center + uncertainty - last_good <= expiry, "map expired at event time")
                    if kind == "display_mapping":
                        candidates = [selected for src, start, stop, selected in selections
                                      if src == source and start <= Decimal(raw) - capture and Decimal(raw) + capture < stop]
                        require(candidates == [map_key], "missing or ambiguous display selection")
                    row["mapping_id"] = use["mapping_id"]
                    row["bound_components_us"] = record["bound_components_us"]
                row.update(raw_us=str(raw), kind=kind, reference=use["reference"],
                           mapped_us=text_decimal(center), uncertainty_us=text_decimal(uncertainty),
                           mapping_bound_us=text_decimal(mapping_bound),
                           lower_us=text_decimal(center - uncertainty), upper_us=text_decimal(center + uncertainty))
                row["status"] = "valid" if mapping_bound <= gate else "uncertain"
                require(row["status"] == "valid", "mapping uncertainty exceeds gate")
                valid[key] = (ref, center, uncertainty)
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                row["reason"] = str(exc)
                errors.append("clock use: " + str(exc))
        require(required <= seen, "missing expected runtime mapping use")
        for pair in objects(config.get("durations", []), "durations"):
            try:
                start, end = event_key(pair.get("start")), event_key(pair.get("end"))
                require(start in valid and end in valid, "duration endpoint has no valid mapping")
                ref_a, a, u_a = valid[start]
                ref_b, b, u_b = valid[end]
                require(ref_a == ref_b, "duration crosses reference epochs")
                center, bound = b - a, u_a + u_b
                durations.append({"start": pair["start"], "end": pair["end"],
                                  "center_us": text_decimal(center), "uncertainty_us": text_decimal(bound),
                                  "lower_us": text_decimal(center - bound), "upper_us": text_decimal(center + bound),
                                  "strictly_after": center - bound > 0})
            except (ValueError, KeyError, TypeError) as exc:
                errors.append("clock duration: " + str(exc))
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        errors.append("clocks: " + str(exc))
    result["complete_evidence"] = not errors
    return result, errors


def batch_key(value):
    return (identifier(value.get("game_session_id")), str(unsigned(value.get("writer_epoch"))),
            str(unsigned(value.get("batch_id"))))


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None, "invalid payload/configuration digest")
    return value


PIPELINE_EVENTS = {"ball_query_send", "ball_query_receive", "state_update_send",
                   "state_commit_receive", "state_publication", "feedback_send"}


def audit_pipeline(header, events):
    """Audit declared batch provenance, never simulate physics or tennis rules."""
    config = header.get("pipeline_audit")
    if config is None:
        return None, []
    errors, summaries = [], []
    result = {"batches": summaries, "complete_evidence": False}
    try:
        require(isinstance(config, dict), "pipeline_audit must be an object")
        pi, game = binding(config.get("physics")), binding(config.get("game"))
        require(pi != game, "physics and game must have distinct bindings")
        expected = {}
        for entry in objects(config.get("batches"), "expected batches"):
            key = batch_key(entry)
            require(key not in expected, "duplicate expected batch")
            expected[key] = entry
            unsigned(entry.get("roster_revision"))
            unsigned(entry.get("rules_revision"))
            digest(entry.get("configuration_sha256"))
        require(bool(expected), "pipeline audit needs expected batches")
        grouped = defaultdict(lambda: defaultdict(list))
        for event in events:
            if event["event"] not in PIPELINE_EVENTS:
                continue
            try:
                key = batch_key(event["details"])
                require(key in expected, "unknown batch/session/writer epoch")
                require(binding(event) == (game if event["event"] == "state_publication" else pi), "pipeline producer binding mismatch")
                grouped[key][event["event"]].append(event)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append("pipeline record: " + str(exc))
        committed_versions = set()
        committed_transactions = set()
        for key, manifest in expected.items():
            row = {"game_session_id": key[0], "writer_epoch": key[1], "batch_id": key[2], "status": "incomplete"}
            summaries.append(row)
            stages = grouped[key]
            try:
                def single(name):
                    values = stages.get(name, [])
                    require(bool(values), "missing " + name)
                    payloads = {json.dumps(event["details"], sort_keys=True) for event in values}
                    require(len(payloads) == 1, "conflicting duplicate " + name)
                    return min(values, key=lambda item: unsigned(item["event_seq"]))

                query, response = single("ball_query_send"), single("ball_query_receive")
                qd, rd = query["details"], response["details"]
                entries = objects(qd.get("queries"), "queries")
                require(len(entries) <= 8, "more than eight queries")
                query_keys, txs = {}, []
                for entry in entries:
                    query_id = str(unsigned(entry.get("query_id")))
                    tx = transaction_key(entry.get("transaction"))
                    require(query_id not in query_keys and tx not in txs, "duplicate query/transaction")
                    query_keys[query_id] = tx
                    txs.append(tx)
                    starts = [event for event in events if event["event"] == "transaction_start"
                              and event.get("transaction") == entry["transaction"]]
                    require(len(starts) == 1, "query has no unique source transaction")
                require(all(count <= 2 for count in Counter(tx[0] for tx in txs).values()), "more than two queries per controller")
                require(rd.get("queries") == entries, "response does not echo ordered queries")
                for feedback in stages.get("feedback_send", []):
                    fd = feedback["details"]
                    require(transaction_key(feedback.get("transaction")) in txs, "feedback references an unknown query transaction")
                    require(isinstance(fd.get("committed"), bool), "feedback committed flag must be explicit")
                    require(fd.get("outcome") in ("hit", "miss", "invalid_input", "tracking_unavailable", "stale_input",
                                                   "state_conflict", "timeout", "overloaded", "internal_error"),
                            "unknown feedback outcome")
                    require(fd.get("committed") == (fd.get("outcome") in ("hit", "miss")),
                            "feedback outcome disagrees with committed flag")
                require(unsigned(query["event_seq"]) < unsigned(response["event_seq"]), "response precedes query")
                require(isinstance(rd.get("accepted"), bool), "query acceptance must be explicit")
                if not rd["accepted"]:
                    identifier(rd.get("reason"))
                    require(not any(stages.get(name) for name in ("state_update_send", "state_commit_receive", "state_publication")),
                            "rejected query proceeds to update/commit")
                    require(all(event["details"].get("committed") is False for event in stages.get("feedback_send", [])),
                            "rejected query has committed feedback")
                    row["status"] = "query_rejected"
                    continue
                base, base_tick = unsigned(rd.get("state_version")), unsigned(rd.get("simulation_tick"))
                update, commit = single("state_update_send"), single("state_commit_receive")
                ud, cd = update["details"], commit["details"]
                require(unsigned(response["event_seq"]) < unsigned(update["event_seq"]) < unsigned(commit["event_seq"]), "query/update/commit order violated")
                require(unsigned(ud.get("base_state_version")) == base, "stale candidate base version")
                tick = unsigned(ud.get("simulation_tick"))
                require(tick > base_tick, "candidate tick does not advance")
                digest(ud.get("payload_sha256"))
                for field in ("roster_revision", "rules_revision", "configuration_sha256"):
                    require(ud.get(field) == manifest[field], "stale setup " + field)
                decisions = objects(ud.get("decisions"), "decisions")
                rejected = objects(ud.get("rejected_queries", []), "rejected queries")
                require(len(decisions) <= 8, "too many decisions")
                accounted, decision_txs = set(), []
                for index, decision in enumerate(decisions):
                    query_id = str(unsigned(decision.get("query_id")))
                    tx = transaction_key(decision.get("transaction"))
                    require(query_keys.get(query_id) == tx and query_id not in accounted, "decision query/transaction mismatch")
                    require(unsigned(decision.get("event_index")) == index, "noncontiguous decision indices")
                    require(decision.get("outcome") in ("hit", "miss"), "technical failure cannot be committed decision")
                    accounted.add(query_id)
                    decision_txs.append(tx)
                for rejection in rejected:
                    query_id = str(unsigned(rejection.get("query_id")))
                    require(query_id in query_keys and query_id not in accounted, "rejected query is unknown/duplicated")
                    require(rejection.get("outcome") in ("invalid_input", "tracking_unavailable", "stale_input", "state_conflict", "timeout", "overloaded", "internal_error"), "invalid query rejection")
                    accounted.add(query_id)
                order = {entry["query_id"]: index for index, entry in enumerate(entries)}
                decision_order = [order[decision["query_id"]] for decision in decisions]
                require(decision_order == sorted(decision_order), "decisions reorder the queried inputs")
                require(accounted == set(query_keys), "query disappeared from decision/rejection accounting")
                rules = objects(ud.get("rule_events"), "rule events")
                require(len(rules) <= 16, "more than sixteen rule events")
                for index, rule in enumerate(rules, 8):
                    require(unsigned(rule.get("event_index")) == index, "rule event index outside contiguous 8..23 namespace")
                    identifier(rule.get("kind"))
                    require(isinstance(rule.get("has_cause"), bool), "rule cause must be explicit")
                    if rule["has_cause"]:
                        require(unsigned(rule.get("cause_decision_index")) < len(decisions), "unknown rule cause")
                    else:
                        require("cause_decision_index" not in rule, "causeless rule invents a decision")
                require(isinstance(cd.get("accepted"), bool), "commit acceptance must be explicit")
                require(cd.get("payload_sha256") == ud["payload_sha256"], "commit refers to different candidate")
                if not cd["accepted"]:
                    identifier(cd.get("reason"))
                    require(not stages.get("state_publication"), "rejected commit was published")
                    require(not any(event["details"].get("committed") is True for event in stages.get("feedback_send", [])), "feedback claims rejected commit")
                    row["status"] = "rejected"
                    continue
                version = unsigned(cd.get("state_version"))
                require(version == base + 1 and unsigned(cd.get("simulation_tick")) == tick, "commit version/tick mismatch")
                state_key = (key[0], version)
                require(state_key not in committed_versions, "two batches claim one committed version")
                committed_versions.add(state_key)
                for tx in decision_txs:
                    require(tx not in committed_transactions, "transaction committed by multiple batches")
                    committed_transactions.add(tx)
                publication = single("state_publication")["details"]
                for field in ("state_version", "simulation_tick", "payload_sha256"):
                    require(publication.get(field) == cd.get(field), "publication differs from accepted commit")
                for field in ("decisions", "rule_events", "roster_revision", "rules_revision", "configuration_sha256"):
                    require(publication.get(field) == ud.get(field), "publication changed candidate " + field)
                feedback = stages.get("feedback_send", [])
                for decision, tx in zip(decisions, decision_txs):
                    matches = [event for event in feedback if event.get("transaction") == decision["transaction"]]
                    require(bool(matches), "missing committed feedback")
                    for event in matches:
                        fd = event["details"]
                        require(unsigned(event["event_seq"]) > unsigned(commit["event_seq"]), "feedback precedes commit acceptance")
                        require(fd.get("committed") is True and fd.get("outcome") == decision["outcome"]
                                and fd.get("event_index") == decision["event_index"]
                                and fd.get("state_version") == cd["state_version"]
                                and fd.get("simulation_tick") == cd["simulation_tick"], "feedback commit identity mismatch")
                    received = [event for event in events if event["event"] == "application_response"
                                and event.get("transaction") == decision["transaction"]]
                    for event in received:
                        rd_local = event["details"]
                        require(rd_local.get("committed") is True and batch_key(rd_local) == key
                                and rd_local.get("outcome") == decision["outcome"]
                                and rd_local.get("event_index") == decision["event_index"]
                                and rd_local.get("state_version") == cd["state_version"]
                                and rd_local.get("simulation_tick") == cd["simulation_tick"], "controller response commit identity mismatch")
                for event in feedback:
                    require(transaction_key(event.get("transaction")) in decision_txs
                            or event["details"].get("committed") is False, "unmatched committed feedback")
                row.update(status="accepted", decisions=len(decisions), rule_events=len(rules), state_version=str(version))
            except (ValueError, KeyError, TypeError) as exc:
                errors.append("pipeline " + "/".join(key) + ": " + str(exc))
        for event in events:
            if event["event"] == "application_response":
                if event["details"].get("outcome") in ("hit", "miss"):
                    require(transaction_key(event.get("transaction")) in committed_transactions,
                            "gameplay response has no accepted decision")
                else:
                    require(event["details"].get("committed") is False,
                            "technical response must explicitly be uncommitted")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append("pipeline: " + str(exc))
    result["complete_evidence"] = not errors
    return result, errors
