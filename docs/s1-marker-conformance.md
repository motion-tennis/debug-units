# S1 offline marker-link conformance handoff

This records the initial marker slice. The subsequent [clock/pipeline handoff](s1-clock-pipeline.md) adds the remaining offline profiles and fixes the Windows documentation-check limitation recorded below. Its evidence and task-branch delivery supersede the initial uncommitted status; no shared stage is advanced.

[Repository home](../README.md) · [Profile](trace-format.md#offline-marker-conformance-profile) · [Implementation plan](implementation-plan.md)

## Task brief

- Task/contributor: implement the first bounded S1 debug handoff for the project user's debug responsibility; Codex implementation, authorized in the chat on 2026-11-08.
- Scope: auditor extension, synthetic marker fixture, focused tests, coverage documentation and central implementation status. No later-stage exception.
- Branch: `task/s1-marker-conformance` in both repositories. Remote `origin` fetched successfully before changes; debug base `62d4cb36498bc8f3f2496fa12c62c166efd7d046`, documentation/status base `3260994598f492def82abba6046b8fda78257bc6`. Existing `Elias` branches remain preserved. Changes are local and uncommitted; no push authorized or performed.
- Stage: S1 remains active/incomplete. The accepted S0 v0.3 baseline and `webcam-pi3-doubles-v3` profile are unchanged.
- Schema/profile SHA-256 (canonical LF bytes): `b6728e240316e957f5c5addb973f12f9a57fffbcdacc4331f3db5e06895f360b` / `a3533462fdebfd4c7c2f87eaa3bd579d3056170e3dcfc6a6c68ed34474c1d969`. Windows checkout CRLF bytes differ; no schema/profile modification was made.
- Outcome: explicitly linked markers receive offline conformance checks, with honest unresolved/loss/failure accounting and unchanged sample latency populations.
- Dependencies: trace-v1 and central marker rules at the pinned revision; the fixture provides source/session registry, capture provenance, observation window, independent capture count and link rule. These are synthetic declarations, not verified firmware exports.
- Deferred: live collection, viewer, clock fitting/maps, packet decoding, full-path correlation, marker latency statistics, match auditing and hardware measurements.

## Evidence and reproduction

From `debug-units`, use Python 3.9+ and the standard library:

```sh
python -B -m unittest discover -s tests -v
python -B scripts/check_trace.py examples/synthetic-trace.jsonl
python -B scripts/check_trace.py examples/marker-trace.jsonl
python -B ../documentation/scripts/check_docs.py
git diff --check
```

The original fixture retains five starts, three application results, one censored timeout, one drop and no integrity errors. The marker fixture has one captured/resolved marker, one started transaction and one `miss` response, with complete supported local evidence. Its response latency is synthetic. Focused tests also cover unresolved timing, malformed metadata, wrong sessions/clocks, reboot, unknown targets, duplicate/conflicting links, shared targets, failed targets, attempted relinking, observation cutoff, absent registered sources, trace loss and reordered file records. Missing downstream pipeline stages remain outside this task; a missing target terminal is explicitly incomplete.

The marker fixture SHA-256 is `dcde2966757b410e1d8dfbe8353f4a8c6fd99b68d426a1b7ddc96ce015e8cd2a` (LF bytes). Saved CLI reports and the final validation result are in [S1 evidence](../evidence/s1-marker-results.json).

Validation on Windows, 2026-11-08: all 34 unit tests passed (nine existing and 25 marker tests); both CLI fixtures exited zero. `git diff --check` passed in both repositories. The documentation checker inspected 54 Markdown files but failed with 16 pre-existing S0 freshness errors: native Windows path separators differ from saved POSIX inventory keys, and checkout CRLF bytes differ from recorded LF hashes. An independent comparison of all 15 recorded source hashes against `git show HEAD:<path>` and LF-normalized working copies found no content/hash differences. The freshness checker and historical evidence were left unchanged. Four unavailable sibling repositories were skipped, not validated. No hardware, network, clock-map or gameplay acceptance was performed.

The checker loads a bounded file into memory and scans observed samples for each marker. It is not a streaming service. Full hardware trigger settings and truthfulness of declared counts/capture bounds are not verified. The new field names specialize existing trace-v1 metadata; producers must review this profile before adoption. No gameplay wire field or runtime component is changed.

## Next steps and dependencies

1. Review/adopt the offline metadata profile with the controller owner before implementing a live exporter. Controller must eventually supply truthful session IDs, IRQ boundary/uncertainty, sample capture provenance, association/calibration, capture counts and explicit unresolved links. Board/pins, Zephyr driver and shared-INT behavior require device evidence.
2. Next independent S1 debug slice: known-answer Pi-map validity/epoch/uncertainty fixtures and offline checks. Synthetic work can start without hardware; actual mapping authority and exports belong to physics.
3. Separate S1 slice: transaction/query/batch/commit and full-match provenance checks against accepted contract fixtures, coordinated with physics and game. Do not implement their scoring or state ownership here.
4. S2, after shared release: bounded collector and isolated exports, measured loss/overhead and device/transport evidence. This needs producer implementations and target hardware access.
5. S3, after shared release: one-controller complete-path timeline and integration evidence. This needs controller, tracking, physics and state-service runtimes plus real time-map evidence. S4 expands to four-player traces; S5 supplies matched workload/network measurements.

This task adds local S1 evidence only. Map/match work and other component deliverables remain outstanding; the global S1 gate is not accepted by this handoff.
