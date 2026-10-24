# Normalized trace-v1 format and audit contract

[Repository home](../README.md) · [Central debug architecture](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md)

**Implemented:** the offline auditor reads this normalized JSONL format. **Designed, not implemented:** component emitters and the live collector exporting it. This trace format is separate from the gameplay wire protocol. It does not introduce a gameplay message or a synchronous dependency on the collector.

## Encoding and clocks

Use UTF-8 JSON Lines: one run header followed by event objects, one object per line. Blank lines are ignored. Duplicate JSON keys and non-finite JSON values are rejected. Integer counters and microsecond timestamps are canonical unsigned 64-bit decimal strings: `"0"` or a sequence starting with `1` through `9`, with no sign or leading zeros. Identifiers are nonempty strings of at most 128 UTF-8 bytes.

The collector performs a lossless normalization of gameplay identifiers: numeric wire IDs become decimal strings and 16-byte session/run IDs become lowercase 32-character hexadecimal strings. Preserve any human-readable device labels in separate descriptor metadata. The supplied synthetic fixture uses explicit illustrative names instead of claiming to contain real wire UUIDs. A compact binary trace exporter may use dictionary indices internally; the exported JSONL must resolve them consistently and retain the original identity.

Keep original monotonic timestamps. Event records from different sources may arrive in any order; a merged file's line order is not causal order. `event_seq` starts at zero for each `(run_id, source_id, source_session_id)` and increases once per emitted record. Sequence gaps indicate missing evidence; duplicate sequences are invalid. The original producer sequence survives export and merge. Do not renumber a damaged trace to hide missing records.

The local `t0`, `tr`, and eligible `t1` must use the same controller session and `clock_id`. Source clocks are not implicitly synchronized. Collector arrival timestamps, pcap timestamps, simulation ticks and mapped experiment time belong in separate named metadata. The current checker never subtracts a Pi/PC timestamp from an ESP32 timestamp and does not validate clock mappings.

## Run header

The first nonempty record must contain:

| Field | Type and semantics |
| --- | --- |
| `record_type` | Exact string `run` |
| `trace_version` | Exact string `1` |
| `run_id` | Unique experiment identifier |
| `synthetic` | Boolean; true for generated/replayed test evidence that is not a live hardware run |
| `response_deadline_us` | Positive decimal string; response target used for reporting |
| `electrical_deadline_us` | Positive decimal string; eligible-output target used for reporting |
| `transaction_timeout_us` | Positive decimal string; controller expiry boundary |

Additional manifest metadata is allowed. The reference targets below are provisional: p99 response at most 30 ms, p99 eligible electrical feedback at most 40 ms, with controller expiry at 50 ms. Reporting target exceedances is distinct from enforcing expiry. Targets are not measured performance or proven worst-case limits.

Map the central reference profile's `timing_us.response_p99_target` to `response_deadline_us`, `electrical_p99_target` to `electrical_deadline_us`, and `controller_expiry` to `transaction_timeout_us`, converting integers to decimal strings. Retain the profile ID and file hash in the full manifest. The auditor uses the supplied header values rather than silently overriding them with current defaults.

```json
{"record_type":"run","trace_version":"1","run_id":"synthetic-four-controller-example","synthetic":true,"response_deadline_us":"30000","electrical_deadline_us":"40000","transaction_timeout_us":"50000"}
```

The full run manifest must also retain hardware, software revisions, protocol/profile, camera/tracking configuration, active controller count, duration, workload and fault seed, calibration and clock mapping. Those fields are not yet automatically validated by the small auditor.

## Event record

| Field | Required meaning |
| --- | --- |
| `record_type` | Exact string `event` |
| `run_id` | Same run as the header |
| `source_id` | Producer component/device identity |
| `source_session_id` | Producer boot/process session, not the controller session copied from another device |
| `event_seq` | Source sequence described above |
| `clock_id` | Producer clock domain for this timestamp |
| `mono_us` | Original producer monotonic event timestamp in microseconds |
| `event` | Named event; core events below have audit semantics |
| `transaction` | `{controller_id, session_id, request_seq}` or explicit null; `session_id` here is the controller boot/session |
| `details` | Object containing event-specific fields and optional provenance |

The three transaction fields form the complete measurement key. `request_seq` is a decimal string. Controller-local accounting events must have `source_id == controller_id` and `source_session_id == transaction.session_id`; a physics trace cannot masquerade as controller response reception.

```json
{"record_type":"event","run_id":"synthetic-four-controller-example","source_id":"controller-1","source_session_id":"controller-1-boot-a","event_seq":"0","clock_id":"controller-1-clock","mono_us":"1000000","event":"transaction_start","transaction":{"controller_id":"controller-1","session_id":"controller-1-boot-a","request_seq":"1"},"details":{"imu_sample_ids":["101"]}}
```

## Core event semantics

| Event | Meaning and details |
| --- | --- |
| `transaction_start` | Controller `t0`; exactly one per measurement; preserve sample IDs in details |
| `application_response` | Complete response receipt `tr`, retained only after protocol, identity, validity and expiry checks; details require `outcome` and `electrical_output` |
| `transaction_timeout` | Local terminal outcome when no valid response arrived before the configured expiry; no fabricated `tr` |
| `input_dropped` | Local terminal rejection before send/admission; preserve the started measurement and reason |
| `electrical_feedback` | First electrical activation for the one declared metric output; details require matching `output` and `cue_id` |
| `feedback_suppressed` | Eligible cue intentionally suppressed, for example because its output deadline expired; matching `output` and `cue_id`; preserve reason |
| `response_discarded` | Late, duplicate, malformed or wrong-session receipt; diagnostic only, not another terminal outcome or actuation |
| `fault_output` | Local timeout/disconnect fault indication; not electrical feedback resulting from an application response |
| `log_drop` | Diagnostic source loss record; details `count` is a decimal-string loss delta since the previous reported loss record |

`application_response.details.outcome` is `hit`, `miss`, `invalid_input`, `tracking_unavailable`, `stale_input`, `state_conflict`, `timeout`, `overloaded`, or `internal_error`. An application-reported timeout is an explicit response with `tr`; a controller-local timeout is censored and has no `tr`.

`electrical_output` must explicitly be `led`, `motor`, or null. Null means the response is not eligible for a separately timed electrical cue. This is essential when each controller produces 200 sample transactions per second: it does not imply a physical vibration pulse per sample. Normal status LED levels can persist without a new edge. Semantic hit/swing-end cues and distinct fault indications follow the central feedback policy.

An eligible response also requires a unique `cue_id`. Record exactly one matching first actuation or suppression. The checker rejects repeated activation and activation after expiry. A multi-pulse LED pattern has one first-activation metric; later transitions are separate diagnostic stage events. Preserve additional `t_led`/`t_motor` observations as named stages if both outputs matter; do not mix output populations silently.

```json
{"record_type":"event","run_id":"synthetic-four-controller-example","source_id":"controller-2","source_session_id":"controller-2-boot-a","event_seq":"1","clock_id":"controller-2-clock","mono_us":"1032000","event":"application_response","transaction":{"controller_id":"controller-2","session_id":"controller-2-boot-a","request_seq":"1"},"details":{"outcome":"miss","electrical_output":null}}
```

## Pipeline stages and batch correlation

Other named events are retained as stage evidence. Suggested names include `packet_send`, `packet_receive`, `frame_capture`, `inference_start`, `inference_complete`, `pose_selected`, `fusion_complete`, `ball_query_send`, `ball_query_receive`, `decision_complete`, `state_update_send`, `state_commit_receive`, `feedback_send`, `tick_release`, `render_submit`, and `presentation_observed`.

Include the applicable `message_type`, `message_id`, `batch_id`, `query_id`, `update_id`, `event_id`, `game_session_id`, `writer_epoch`, state version/tick, selected sample/frame IDs, association/calibration, clock-mapping IDs, ages/uncertainty and queue metrics in details. A shared batch query still has a distinct logical query/result for every included transaction. A shared batch-stage event can use `transaction: null` and list the complete member keys in `details.transactions`; retain its original source sequence and timestamp. A viewer joins that event to each member without rewriting it into fictitious separate producer events.

The current auditor verifies core local measurement integrity, not mandatory stage presence, physics correctness, batch ordering, state ownership or payload schemas. Future protocol-aware audit rules must inspect these fields and the complete required ball request/response/commit path before integration is accepted.

## Results and failure interpretation

Run the actual supplied tool from the repository root:

```sh
python3 scripts/check_trace.py examples/synthetic-trace.jsonl
```

It emits a JSON report to standard output. Exit status zero means the supported local trace checks passed. It does **not** mean timing targets, network behavior or hardware acceptance passed. Nonzero means malformed/inconsistent/incomplete local trace evidence; no started measurements is also insufficient evidence.

The report includes started measurements, application results, explicit outcomes, local drops, censored timeouts, pending records, cue eligibility/suppression, source gaps/log loss, per-controller timing, overall and per-outcome response timing, and eligible electrical timing. Median uses the ordinary sample median; p95/p99 use nearest rank. Target exceedances and p99 comparisons are shown separately from the expiry rule. Small fixtures cannot establish a reliable tail estimate.

Timeouts are never inserted into completion percentiles at zero or the deadline. Local drops are not completed responses. Missing terminal records fail audit; discarded late responses cannot create a second completion. An unmatched discarded response from an old session remains a diagnostic event and does not invent a new started transaction. Stage-only references without controller accounting are not audited as completed measurements. Source sequence gaps and reported log drops remain separate counters because they may describe the same missing records and must not be blindly added together.

The provided fixture contains five starts from four controllers, three responses (hit, miss and tracking failure), one censored timeout and one local drop. Its illustrative response median is 20 ms and p99 is 32 ms, including one 30 ms target exceedance. These values are intentionally synthetic and are not Motion Tennis benchmarks.
