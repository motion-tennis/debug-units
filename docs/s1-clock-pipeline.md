# S1 offline clock and pipeline conformance

[Repository home](../README.md) · [Trace format](trace-format.md) · [Marker handoff](s1-marker-conformance.md)

## Task and scope

The project user authorized the remaining S1 debug checks, Windows documentation-check repair, review, commit and task-branch publication on 2026-11-08. Work continues on `task/s1-marker-conformance`, based on debug `62d4cb36498bc8f3f2496fa12c62c166efd7d046` and documentation `3260994598f492def82abba6046b8fda78257bc6`, with the existing marker changes preserved. Both remotes were fetched before continuing. S1 remains active; no later-stage exception or gate acceptance is claimed.

Allowed paths: debug auditor, fixture/test/evidence files and related documentation; central freshness checker/tests and affected status/design documentation. Gameplay schema/profile and component runtimes are unchanged. Accepted v0.3 schema/profile hashes are recorded in the marker handoff. This document defines a bounded offline specialization of existing trace metadata, not a live producer contract accepted by the other repository owners.

## Clock profile

An optional `clock_audit` header activates validation; absent metadata leaves this extension disabled. Its fields are `mapping_gate_us` (positive decimal string), `expiry_us` (positive unsigned decimal string), `uses`, optional `expected_runtime_events`, `display_selections` and `durations`. Event references contain `source_id`, `source_session_id`, `event_seq`; source/reference bindings contain `source_id`, `source_session_id`, `clock_id`. Original raw events are never rewritten. The fixture declares the existing reference gates of 2000 microseconds and 5000000 microseconds; these are not measured performance.

`clock_maps` is a header array of immutable accepted records. Each record requires:

| Fields | Offline meaning |
| --- | --- |
| `mapping_id`, `source`, `reference` | Unique map within its complete Pi epoch, bound to one source session/clock |
| `units`, `a`, `b` | `microseconds`, positive affine scale and signed offset in `T_pi = a * t_source + b` |
| `anchor_us`, `valid_from_us`, `valid_until_us` | Source-clock anchor and inclusive validity interval |
| `accepted_reference_us`, `last_good_reference_us` | Pi-time acceptance and latest accepted exchange; rejected fits do not refresh either |
| `method_revision`, `status` | Named fitting configuration, `valid` accepted map; fitting itself is outside this checker |
| `bound_components_us`, `growth_ppm` | Named nonnegative Pi-time bounds plus nonnegative rate-bound growth from the source anchor; null means unknown and prevents valid conversion |
| Optional `invalid_after_source_us` | Exclusive effective source-time boundary; later invalidation preserves earlier valid history |

Affine numbers/bounds are finite decimal strings of at most 32 characters and magnitude between 1e-30 and 1e30, or zero. Raw counters/timestamps remain unsigned 64-bit strings. Decimal arithmetic uses 80-digit precision. Each referenced event declares `details.capture_uncertainty_us`; unknown capture timing remains invalid for conversion. Total uncertainty is the sum of map components, `growth_ppm * abs(t-anchor)/1000000`, and `abs(a) * capture_uncertainty`. Full capture intervals must fit validity/invalidation boundaries; the mapped interval must follow map acceptance and fit the age limit since the last good exchange. Only the mapping component is compared with the mapping accuracy gate; capture uncertainty remains separately visible.

Each `uses` entry names an event, `reference`, `mapping_id` and `kind: runtime_mapping_use` or `display_mapping`. Runtime uses must reference the exact Pi-selected version; no newest-map fallback exists. `expected_runtime_events` detects missing uses and prohibits replacing one with a display assignment. A display selection names source/reference/map and a half-open `from_us`/`until_us` interval. Selections for one source must not overlap, including across reference epochs; the event's full capture interval must fit one unique selection. `pi_native` uses omit `mapping_id` and require exact source/reference equality, retaining capture uncertainty.

`durations` entries reference `start` and `end` events. Only valid conversions into the same Pi epoch produce a duration. The report preserves center, conservative summed uncertainty, lower/upper bounds and `strictly_after`; negative or overlapping intervals are never clamped. Unknown/expired/wrong-session mappings yield a reason and no valid cross-device duration. An over-gate finite conversion is labeled `uncertain`, with its numerical interval retained. Raw local response/electrical distributions remain unchanged.

Limits: this checks declared bounds and applicability, not the truth of fit/asymmetry/capture claims, raw exchange fitting, hardware accuracy, or real-time map publication. Rejected-fit diagnostic events do not overwrite the accepted registry. General lifecycle records are not automatically converted into this offline effective-boundary field; exporters must preserve that provenance for review. Test data is synthetic.

## Pipeline and match provenance profile

An optional `pipeline_audit` header declares distinct `physics` and `game` producer bindings plus a nonempty `batches` array. Each expected batch has `game_session_id`, unsigned `writer_epoch`/`batch_id`, `roster_revision`, `rules_revision`, and a 64-character lowercase `configuration_sha256`. Declaring expected batches detects completely missing paths. Event `details` retain the batch key throughout. The fixture uses normalized trace metadata, not decoded wire messages.

| Event | Producer and required details |
| --- | --- |
| `ball_query_send` | Pi: ordered `queries`, each with unsigned `query_id` and complete `transaction` |
| `ball_query_receive` | Pi's complete response receipt: exact ordered query echo, Boolean `accepted`; accepted responses have `state_version`, `simulation_tick`, rejected responses have `reason` |
| `state_update_send` | Pi: `base_state_version`, advancing `simulation_tick`, setup revisions/digest, `payload_sha256`, `decisions`, optional `rejected_queries`, `rule_events` |
| `state_commit_receive` | Pi's received game acknowledgement: Boolean `accepted`, candidate `payload_sha256`; accepted result version/tick, or rejection `reason` |
| `feedback_send` | Pi: target in top-level `transaction`; explicit `committed` and `outcome`; successful feedback also names `event_index`, committed version/tick |
| `state_publication` | Game: accepted version/tick, candidate digest, setup identity, unchanged decisions and rule events |

There are at most eight queries and two per controller, with unique query/transaction keys. Each query must reference an observed unique start. A decision repeats query/transaction identity, uses contiguous indices 0..7 and outcome `hit` or `miss`, preserving query order. A removed query is explicitly listed once in `rejected_queries` with its `query_id` and technical error outcome. No input may disappear or appear twice. Rule events have contiguous indices 8..23 (maximum sixteen), a named `kind`, Boolean `has_cause`, and a valid `cause_decision_index` only when a cause exists. Rule kinds and complete match-state contents remain opaque here; this is provenance checking, not tennis-rule validation.

Pi source sequence establishes query/response/update/commit/feedback order without subtracting clocks. Candidates use the queried base and advance the tick; an accepted commit advances the version by exactly one. Conflicting duplicates are rejected; identical retries reuse one outcome. Separate batches cannot claim the same committed version or commit a transaction twice. Publications must match accepted state identity and event lists. Feedback must refer to an admitted query and follow acceptance; any controller `application_response` for a successful decision must preserve its commit identity. A local timeout/drop can coexist with a later accepted commit without becoming a fabricated completion.

Rejected queries cannot proceed to updates, commits or publications. Rejected commits cannot publish or emit committed feedback. Technical responses are explicitly uncommitted; an ordinary hit/miss cannot exist without an accepted decision. A periodic-only batch retains the required query/response and can commit rules with zero decisions, never fake controller transactions. The core auditor still requires at least one measurement in the overall run; a purely periodic file is not sufficient measurement evidence.

Limits: digests are correlated declarations, not recomputed wire hashes. The checker does not establish full ball/avatar/score payload correctness, physics calculations, rollback internals, global state-store serializability, tracking freshness, actual network delivery or bounded runtime storage. Publication is observed on the game clock and is not ordered against Pi timestamps without separate map evidence. A passing offline report is not a running doubles game.

## Reproduction and handoff

```sh
python -B -m unittest discover -s tests -v
python -B scripts/check_trace.py examples/clock-trace.jsonl
python -B scripts/check_trace.py examples/pipeline-trace.jsonl
python -B ../documentation/scripts/check_docs.py
git diff --check
```

The saved [S1 conformance evidence](../evidence/s1-conformance-results.json) includes actual CLI reports, fixture SHA-256 hashes and validation results. Keep all existing marker/core tests. The Windows freshness checker now compares portable inventory paths and permits LF identities for CRLF text checkouts while still detecting substantive content changes; historical S0 evidence is unchanged.

Validation on Windows: 72 debug tests and ten documentation freshness tests passed, and all four example traces exited zero. Local documentation and whitespace checks pass. The four unavailable component checkouts remain unverified skips. No runtime/device benchmark was run. Changes are delivered through the named task branches; remote `main` is reserved to the project user. The marker-only evidence file retains its historical 34-test result and the then-unfixed Windows limitation; the conformance evidence is the current result.

Repository owners can review the runnable fixtures directly:

- **Controller:** [marker profile](trace-format.md#offline-marker-conformance-profile), raw sample/IRQ capture, configuration/session/association identity, truthful capture counts/uncertainty, explicit unresolved links and committed response identity.
- **Physics:** immutable Pi maps and exact use/selection bindings, historical validity, query/update/ack/feedback provenance and explicit query rejection accounting.
- **Game:** committed publication identity, setup revisions and unchanged decision/rule lists; no debug dependency in the state writer.
- **Tracking:** original capture/session/clock identity and characterized capture uncertainty; real pose/association evidence remains for integration.

The user confirmed these repository boundaries but supplied no named reviewers or review channel. No messages, issues or review requests were sent externally. Owner acceptance and real exporter compatibility remain open, explicitly separate from tested offline implementation. The next dependency is review/adoption of these profiles and representative real export samples. S2 collection and S3 live timeline still require shared gate release and component/device evidence.
