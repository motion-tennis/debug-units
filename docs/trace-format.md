# Normalized trace-v1 format and audit contract

[Repository home](../README.md) · [Central debug architecture](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md)

**Implemented:** the offline auditor reads this normalized JSONL format. **Designed, not implemented:** component emitters and the live collector exporting it. This trace format is separate from the gameplay wire protocol. It does not introduce a gameplay message or a synchronous dependency on the collector.

## Encoding and clocks

Use UTF-8 JSON Lines: one run header followed by event objects, one object per line. Blank lines are ignored. Duplicate JSON keys and non-finite JSON values are rejected. Integer counters and microsecond timestamps are canonical unsigned 64-bit decimal strings: `"0"` or a sequence starting with `1` through `9`, with no sign or leading zeros. Identifiers are nonempty strings of at most 128 UTF-8 bytes.

The collector performs a lossless normalization of gameplay identifiers: numeric wire IDs become decimal strings and 16-byte session/run IDs become lowercase 32-character hexadecimal strings. Preserve any human-readable device labels in separate descriptor metadata. The supplied synthetic fixture uses explicit illustrative names instead of claiming to contain real wire UUIDs. A compact binary trace exporter may use dictionary indices internally; the exported JSONL must resolve them consistently and retain the original identity.

Keep original monotonic timestamps. Event records from different sources may arrive in any order; a merged file's line order is not causal order. `event_seq` starts at zero for each `(run_id, source_id, source_session_id)` and increases once per emitted record. Sequence gaps indicate missing evidence; duplicate sequences are invalid. The original producer sequence survives export and merge. Do not renumber a damaged trace to hide missing records.

The local `t0`, `tr`, and eligible `t1` must use the same controller session and `clock_id`. Source clocks are not implicitly synchronized. Collector arrival timestamps, pcap timestamps, simulation ticks and mapped experiment time belong in separate named metadata. The current checker never subtracts a Pi/PC timestamp from an ESP32 timestamp and does not validate clock mappings.

The agreed runtime design maps each source into the Pi reference clock with drift correction. Retain the Pi-issued mapping version used by runtime processing, rather than estimating a separate display mapping. Original `mono_us`, source identity/session/clock and local timing semantics remain unchanged; [planned clock metadata](#pi-reference-clock-metadata) adds provenance without changing the gameplay schema or the auditor's implemented core rules.

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

The full run manifest must also retain hardware, software revisions, protocol/profile, camera/tracking configuration, active controller count, duration, workload and fault seed, calibration and clock mapping. When IMU markers are enabled, retain their configuration and correlation policy as described below. Those fields are not yet automatically validated by the small auditor.

## Pi-reference clock metadata

**Agreed design:** the Pi owns affine mappings `T_pi = a * t_source + b` and the debug view consumes the same versions as runtime processing. **Proposed metadata contract:** a completed run manifest retains an append-only `clock_maps` registry, raw exchange records and mapping lifecycle/use evidence. These metadata structures, fitting, status checks and interval calculations are not implemented or validated by the existing offline auditor. They use manifest metadata and diagnostic event `details`; they do not add a new trace-v1 top-level record type or gameplay message.

Each immutable map record must retain:

| Metadata | Required meaning |
| --- | --- |
| `mapping_id` | Pi-issued immutable map identity, unambiguous within its complete reference epoch; new accepted coefficients or uncertainty model create a new record |
| Source binding | `source_id`, `source_session_id` and `clock_id` to which the conversion applies; another boot or clock cannot reuse it |
| Reference binding | Reference Pi source identity, session and clock identifying the reference epoch; never infer an epoch from similar timer values |
| Affine estimate | `a`, `b`, declared units and a numerical anchor; retain signed offset at that anchor and drift convention `(a - 1) * 1,000,000` ppm |
| Fit and validity evidence | Fit input window, accepted/rejected exchange identities, method/configuration revision, accepted time, last good exchange time and declared validity interval |
| Uncertainty model | Bound components for exchange asymmetry/timestamping/fit error, drift growth over the valid interval, and any other declared source/reference conversion terms; no unknown component becomes zero |
| Lifecycle evidence | Separate time-stamped status/reason and effective validity boundaries; never overwrite a map's historical coefficients or silently rebase earlier events |

When tracking, game and renderer demonstrably use one laptop host clock, they may share verified fit coefficients and exchange evidence. Materialize a separate immutable map record/ID for each producer's source ID/session/clock binding. Never use another process's session-bound record merely because its timer values appear equal; restarting one producer requires a new binding. An independent camera/driver clock still needs its own conversion evidence and capture uncertainty.

Represent signed offsets and possibly fractional coefficients/drift explicitly as metadata with declared units and precision. They are not unsigned source counters or `mono_us`, and must not be passed through the existing unsigned core-field interpretation. Preserve original integer exchange timestamps as decimal strings with each clock's identity and boundary meaning. Future metadata validation must reject non-finite estimates and unexplained negative/unknown bounds; the current parser's acceptance of a `details` object does not enforce those semantics.

The planned coordinator has the Pi initiate the existing TCP `ClockExchange`: preserve Pi send, source receive, source send and Pi complete-response receipt timestamps, plus exchange identity, involved sessions/clocks and acceptance/rejection reason. The fourth time is captured locally by the Pi and retained with the other three in the run bundle. The raw observations support review of offset, drift, delay/asymmetry and outlier handling; neither RTT/2 nor a best-fit residual alone proves a one-way-delay bound. Record exact timestamp placement and fit settings rather than claiming a currently implemented estimator.

When runtime processing maps one event or source sample, its Pi-issued mapping-use record identifies `details.clock_mapping_id`, the full source/reference binding, and the original timestamp plus an unambiguous source event/sample/message key. For a raw trace event that key includes source ID/session and `event_seq`; for a gameplay sample it includes the complete transaction/sample identity and the timestamp field being converted. A shared batch or stage converting several source values uses `details.clock_mapping_refs`, a list of these explicit bindings with a `clock_mapping_id` per entry. The producer's own event timestamp and every referenced source time are separate domains; one map ID cannot stand for the whole batch.

Raw ESP32/laptop emitters need not know the Pi-selected map ID, rewrite their source events or wait for mapping publication. The Pi's association evidence is exported asynchronously and may be materialized as a derived index beside immutable raw events. The viewer joins each original timestamp to that runtime-selected map-use record. Missing references/registry entries remain unresolved; selecting the newest map or fitting the event afterward is not an equivalent reconstruction of runtime behavior. A diagnostic `clock_map_published` stage may carry a new immutable record in `details`; `clock_mapping_status` may carry a state transition. These names and the derived association index are proposed evidence formats only, not implemented runtime hooks.

Trace-only events, including IRQ markers or render diagnostics not converted by physics, may use a separately labeled `display_mapping` in the derived index. For this purpose the Pi exports append-only mapping-selection records: nonoverlapping source-time intervals with complete source/reference binding, activation boundaries and selected map IDs. The viewer applies only a unique assignment within the map's validity/uncertainty window; it does not pick the newest fit. Mark actual processing evidence as `runtime_mapping_use` and give it precedence, including when physics processed an older sample. A missing expected runtime-use reference cannot be filled by display-only evidence. Missing or ambiguous selection records leave trace-only events on local lanes. Later updates must not silently reassign earlier events. These conversion classifications belong to planned metadata, not new top-level trace records. Pi-native events in the declared reference domain use the identity conversion in that epoch while retaining event-capture uncertainty.

Use `initializing`, `valid`, `uncertain`, `expired` and `invalid` as explicit mapping statuses with reasons. The live/source panel shows signed offset at the declared anchor, drift ppm, age of the last good exchange, the uncertainty evaluated at the displayed time, reference epoch and mapping ID. `initializing` means no accepted mapping yet; `uncertain` identifies a known inadequate bound or insufficient evidence; `expired` identifies a time beyond the last accepted map's validity; `invalid` identifies an incompatible epoch/session, discontinuity or unusable mapping. Only `valid` satisfies the configured runtime mapping gate. Unknown evidence cannot be represented by a zero uncertainty; use a reason and unsynchronized local presentation.

Evaluate map applicability and status at each event's time in its reference epoch. Current expiry or a later Pi/controller restart does not retroactively invalidate earlier events within their original validity window. A Pi restart establishes a new reference epoch for all live mappings; a source restart establishes a new source session for that source. Retain old map records, exchange observations and lifecycle boundaries for historical inspection. The map's drift/uncertainty model applies only inside its declared window; never extrapolate past that window or join separate epochs without a separately evidenced mapping.

A rejected candidate fit does not automatically invalidate a previously accepted map that still meets its age, bound and applicability rules. Record the rejection separately and apply any actual discontinuity/invalidation boundary explicitly. The panel's last-good age resets only on accepted evidence, not on a received but rejected exchange.

Mapped events must expose a numerical interval `mapped_time +/- total_uncertainty` on the planned timeline, with visible bands/whiskers and text rather than color alone. A detail view retains raw time/domain, mapped time, map ID, source/reference sessions, event-capture uncertainty and each conversion-bound component. Apply the appropriate unit conversion/scale when combining source-capture uncertainty with the Pi-time mapping bound. A finite but over-limit estimate may appear as `uncertain` within its valid time window; unknown bounds or invalid/expired map use stays on local-clock lanes. Keep identity-based causal links and local measurements in both presentations.

For different-source events A and B mapped into the same valid reference epoch, show the duration center `D = T_B - T_A` and a conservative interval `[D - (U_A + U_B), D + (U_A + U_B)]`, where each `U` includes its applicable mapping and event-capture bounds. Do not assume independent statistical errors or silently cancel correlated components. Two 2 ms mapping bounds contribute `+/- 4 ms` before event-capture bounds; this is illustrative arithmetic, not a measurement. Overlapping event intervals do not establish a total cross-source order. Known causal relations come from IDs, and negative/overlapping duration endpoints must remain visible rather than being clamped into apparent precision. Missing or invalid map evidence means no cross-device duration claim.

Same-source/controller-session `tr - t0`, `t1 - t0` and eligible marker-to-local-endpoint differences continue to use the original local clock and do not need the map. The existing proposed 1 s refresh, 5 s expiry after the last valid update, and 2 ms/source mapping gate remain unchanged; scheduled refreshes, rejected fits and trace receipt do not count as successful updates. Observation loss remains an evidence-loss outcome and is not automatically a gameplay error. Consult the [canonical Pi-reference mapping](https://github.com/motion-tennis/documentation/blob/main/docs/coordinates-and-time.md#pi-reference-clock-mapping) and [ADR 0009](https://github.com/motion-tennis/documentation/blob/main/docs/adr/0009-pi-reference-clock-mapping.md).

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

## Additional IMU threshold markers

**Agreed design:** continuous 200 Hz gameplay sampling and messages remain unchanged. A separate hardware IMU threshold interrupt adds a diagnostic event for tracing a motion/swing candidate. It creates no `transaction_start`, changes no existing sample `t0` or timeout, and does not establish a hit. **Proposed trace extension:** the named diagnostic events and linking policy below use the existing trace-v1 event/details mechanism. Emitters, viewer joins, marker integrity checks and event-latency reports are not implemented by the current auditor.

The complete marker key is `(controller_id, session_id, trigger_id)`, where `session_id` is the controller boot/session and `trigger_id` is a nonempty identifier unique in that session. A monotonically increasing counter encoded with the unsigned decimal-string convention is the recommended allocation. Every producer referencing a marker retains that complete key; never use a bare trigger counter across devices or boots. Do not reuse the physics `swing_id` as an IMU marker ID: several threshold events may belong to one swing, and a threshold event may never become a valid swing.

| Diagnostic event | Timestamp and identity | Required details and meaning |
| --- | --- | --- |
| `imu_threshold_trigger` | Controller producer and clock; `mono_us` is `t_trigger`; `transaction: null` | `trigger_id`, `trigger_config_id`, `trigger_boundary`, `capture_uncertainty_us`; optional `source_imu_sample_id` only when the detector's source sample is known from evidence. `trigger_boundary` distinguishes hardware IRQ-edge capture from timestamping ISR entry. Preserve ISR/edge delay characterization; never relabel task handling or export time as the IRQ. |
| `trigger_link` | Time the association is recorded, in the controller clock; complete target `transaction` for a resolved link | `trigger_controller_id`, `trigger_session_id`, `trigger_id`, `link_status`, `link_rule`, `target_sample_id` and target capture provenance when resolved. An unresolved record uses `transaction: null`, `link_status: unresolved` and a reason; it contains no invented target sample. |

Microsecond uncertainty values use the existing unsigned decimal-string convention when known; an unknown uncertainty is explicit null with a reason. References from other stages or producers use `trigger_controller_id`, `trigger_session_id` and `trigger_id` together in `details`. The trigger record's own controller/session are its `source_id` and `source_session_id`. They must match any explicit marker reference. Source `event_seq` rules and loss accounting apply to both diagnostic events, independent of transaction accounting.

The proposed primary rule `first_capture_at_or_after_trigger` selects the first regular measurement whose capture is known to be at or after `t_trigger` in the controller clock. Record the target sample ID and full transaction key explicitly; a later asynchronous join must not infer them from similar timestamps. If the capture boundary, clock mapping or uncertainty cannot establish which measurement is first, record an unresolved link and preserve the evidence for diagnosis. Hardware detector source-sample provenance, if available, is a separate field and does not silently replace the declared primary rule. Any future alternative link rule must be named and recorded in the run manifest.

Choose the target independently of transmission or processing success. A dropped, expired, invalid or failed target remains the selected transaction; do not move the link to the next successful response. Several distinct markers may point to the same regular transaction and must remain visible as distinct markers. The observer never creates a sample, sends an extra input, raises its priority, changes retries or extends the target's existing 50 ms expiry. At 200 Hz, an ideal periodic stream has a 5 ms interval; actual wait from IRQ to the selected capture/send includes jitter and is measured, not replaced by a fixed 5 ms value.

The planned correlation overlay follows marker -> explicit transaction/sample -> selected pose/frame and fusion -> logical ball query and response -> ordered decision -> atomic update and commit -> matching controller response. An accepted gameplay decision may also link to a semantic `swing_id`, `cue_id`, electrical activation and renderer event. Keep game session, writer epoch, batch/event index, association/calibration and original clock domains. This join uses existing gameplay identities; it does not require a marker field in `motion.proto` or a new gameplay packet. A batch retains all member identities. Rejected input, missing tracking, timeout, missing commit or missing trace stages are visible branch endpoints, not fabricated successful stages.

Preserve these distinct measurement populations:

- **Sample response and electrical latency:** existing `tr - t0` and eligible `t1 - t0`, with unchanged accounting and reference targets.
- **Marker-to-associated-response latency:** `tr_associated - t_trigger`, only for the explicitly linked primary transaction and same controller session/clock. It includes the wait for the selected regular sample and its normal processing path. The next response to arrive may belong to an older transaction and is not a valid substitute.
- **Marker-to-semantic-result or cue latency:** a separately declared endpoint linked by actual swing/event/cue identity, potentially reached by a later transaction. Report the endpoint-selection rule and all intervening evidence. A normal no-contact sample response is not automatically the completion of a swing. An absent/ineligible cue has no fabricated electrical latency.

Marker latencies start at the recorded IRQ boundary. Sensor sampling, filtering, detector duration and physical movement before that boundary require separate characterization. Cross-device stage durations still require clock mappings with uncertainty; original ESP32 end-to-end differences use its local clock. Existing 30/40 ms sample targets and 50 ms transaction expiry do not automatically become marker or whole-swing deadlines. A marker observation cutoff, if used, must be named independently; failure or incomplete evidence never becomes a made-up completion time.

The manifest must retain the IMU and firmware/driver revision; accelerometer/gyro ODR and actual stream cadence; detector evaluation rate and filter path; threshold definition, axes or norm, units and gravity handling; minimum duration; hysteresis/rearm policy; interrupt routing and latching/clearing behavior; IRQ timestamp method and measured uncertainty; `trigger_config_id`; link rule; and any event-observation cutoff. Record which settings the device actually supports rather than inventing hardware hysteresis or an absolute threshold for a change detector. Keep configuration changes versioned and define boundary handling so a marker cannot be attributed to the wrong settings.

Runtime exporters must remain bounded and asynchronous. Count marker captures, linked and unresolved markers, duplicate/invalid links, false or repeated candidates, dropped marker records, missing downstream evidence and target failure outcomes separately. A marker that never produces a confirmed swing is still part of the marker population. Preserve trace-loss counters; a missing marker source cannot be discovered without a declared expected source and local capture counters. Haptic output can itself create sensor motion, so acceptance experiments must test actuator-induced triggers and record any suppression/rearm policy rather than silently removing those records. Compare enabled/disabled marker instrumentation using the same gameplay workload to establish observation overhead.

See the [central marker design](https://github.com/motion-tennis/documentation/blob/main/docs/imu-trigger-markers.md) for the shared requirement. Acceptance of these event names by trace-v1 is not validation of their semantics: the current offline auditor does not enforce the link rules, completeness, configuration metadata or any marker-latency calculation.

## Results and failure interpretation

Run the actual supplied tool from the repository root:

```sh
python3 scripts/check_trace.py examples/synthetic-trace.jsonl
```

It emits a JSON report to standard output. Exit status zero means the supported local trace checks passed. It does **not** mean timing targets, network behavior or hardware acceptance passed. Nonzero means malformed/inconsistent/incomplete local trace evidence; no started measurements is also insufficient evidence.

The report includes started measurements, application results, explicit outcomes, local drops, censored timeouts, pending records, cue eligibility/suppression, source gaps/log loss, per-controller timing, overall and per-outcome response timing, and eligible electrical timing. Median uses the ordinary sample median; p95/p99 use nearest rank. Target exceedances and p99 comparisons are shown separately from the expiry rule. Small fixtures cannot establish a reliable tail estimate.

Timeouts are never inserted into completion percentiles at zero or the deadline. Local drops are not completed responses. Missing terminal records fail audit; discarded late responses cannot create a second completion. An unmatched discarded response from an old session remains a diagnostic event and does not invent a new started transaction. Stage-only references without controller accounting are not audited as completed measurements. Source sequence gaps and reported log drops remain separate counters because they may describe the same missing records and must not be blindly added together.

The provided fixture contains five starts from four controllers, three responses (hit, miss and tracking failure), one censored timeout and one local drop. Its illustrative response median is 20 ms and p99 is 32 ms, including one 30 ms target exceedance. These values are intentionally synthetic and are not Motion Tennis benchmarks.
