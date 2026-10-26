# S0 diagnostic contract review and S1 handoff

[Repository home](../README.md) · [Local workflow](workflow.md) · [Central status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md) · [Shared contract](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md)

## Review scope and evidence

Task: S0 component-side contract review and bounded S1 handoff, 2026-10-26. The starting shared revision is `documentation@95c2592`; this review accompanies the S0 schema/profile revision identified by the exact hashes in the shared evidence. The [S0 baseline](https://github.com/motion-tennis/documentation/blob/main/docs/s0-baseline.md) pins the final contract hashes and codec/size results. The candidate is `motion.v03`, protocol `0.3-proposed`, profile `webcam-pi3-doubles-v3`; [ADR 0011](https://github.com/motion-tennis/documentation/blob/main/docs/adr/0011-full-match-contract-and-state-stream.md) records the full-match state channel. This document records an AI technical review, not a human stage decision or an implemented component. The central ledger alone releases S1.

Allowed work here is documentation only. Shared schema, codec fixtures and resource checks belong in `documentation`; runtime integration and hardware measurements retain their later stage gates. Proposed numerical targets remain unmeasured. No later-stage exception is claimed.

## Producer and consumer expectations

- Join original source/session/clock records by full transaction, query, batch, commit and rule-event identities. Keep roster/configuration revisions and selected sample/pose/map provenance; similar timestamps are not identity evidence.
- Rule events refer to an accepted match commit and retain a stable identity distinct from a sample decision's index. Retry/republication cannot create a second point, serve attempt or avatar change. Technical pauses and sporting events remain distinguishable.
- An IMU marker has its own session-scoped ID and raw trigger boundary; the explicit link chooses the declared regular sample even when that sample fails. Several markers may link to one sample. Missing or ambiguous links stay unresolved, with no added gameplay transaction.
- Consume the same immutable Pi-issued clock map versions used at runtime, retaining native timestamps, source/reference epochs, validity and uncertainty. Missing maps retain local lanes; overlapping mapped intervals do not prove a total time order.
- Collector failure and diagnostic loss cannot block gameplay. Report source gaps, local drop counts, unknown producers and incomplete paths separately; a missing record is never a fabricated successful stage or zero latency.

## Required contract cases

| Case | Expected result and handoff evidence |
| --- | --- |
| Eight-entry full-match commit | Every decision joins its logical query and original transaction; one accepted state version and ordered rule-event identities |
| Duplicate or rejected commit | No duplicate accepted transition; rejected events cannot appear as committed score changes |
| Changed roster/session or reused person number | No join across identity/revision fences; old records remain historical evidence |
| Marker linked to a dropped or timed-out sample | Keep that target and failure; never relink to a later successful sample |
| Shared INT ambiguity / missing marker link | Explicit unresolved evidence and denominator; no invented timing endpoint |
| Expired/wrong-epoch clock map | Preserve local times and reject cross-device duration claims |
| Missing stage, unknown source or trace loss | Report incompleteness; do not infer successful processing |

These are contract acceptance requirements, not claims of current auditor coverage. The supplied `check_trace.py` and nine tests still cover local transaction accounting, clock consistency, expiry/cue integrity and trace-loss evidence only; they do not validate full-match, clock-map or marker semantics.

## First bounded S1 task

**Outcome:** add an offline marker-link conformance slice with synthetic fixtures to the existing auditor, preserving all current core checks. Allow only the parser/audit extension, fixture files, focused tests and coverage documentation. Defer live collection, viewer, clock fitting, network packet capture and gameplay simulation.

**Dependencies:** pinned trace-v1/marker definitions and shared schema/profile hashes; known source/session registry in fixture metadata; an explicit observation cutoff and link rule.

**Acceptance:** a valid explicit marker/sample link; unresolved ambiguous capture; wrong-session and unknown-target rejection; duplicate/conflicting links; multiple distinct markers to one sample; a failed target that stays selected; out-of-order records and source loss with honest incomplete coverage. Test that enabling marker checks changes neither existing transaction counts nor latency populations. Save fixture hashes and actual output. Full-match and map-validity checks are separate later S1 tasks, not implicitly implemented by this slice.

## Review disposition

The diagnostic boundary can represent the full-match contract using existing trace-v1 event/details envelopes and explicit new provenance requirements. Shared codec results validate gameplay messages, not this auditor's planned semantic checks. The S0 review preserves the existing offline tool without adding a collector, viewer or hardware evidence.
