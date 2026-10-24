# Motion Tennis debug units

Observability, reproducible experiments and trace analysis for the complete Motion Tennis path: ESP32 measurement, Raspberry Pi fusion/physics, Windows laptop tracking and game state, and controller feedback. Four players must remain individually identifiable even when physics batches their inputs.

## Implementation status

| Status | Capability |
| --- | --- |
| **Implemented** | Standard-library offline trace auditor, normalized trace-v1 documentation, synthetic JSONL fixture and integrity tests |
| **Designed, not implemented** | Bounded runtime trace emitters, asynchronous live collector, packet decoder, timeline viewer, simulator/replay/fault harness and run-bundle export |
| **Proposed reference profile** | Windows laptop collector; source-local buffers on ESP32/Pi/PC; asynchronous trace transport separate from gameplay; 30 ms response p99 and 40 ms eligible electrical p99 targets, 50 ms controller expiry |
| **Not verified** | Actual packet captures, hardware timing, four-controller capacity, clock mapping, camera latency or real-time guarantees |

The fixture is synthetic. A passing trace audit establishes only the checks implemented by the auditor, never a working or deadline-compliant game.

## Responsibilities and boundaries

- Preserve original timestamps, source clocks, transaction IDs, sample/frame provenance, state versions and batch identities.
- Make response time, electrical feedback, data freshness, queueing, state conflicts, simulation lag and failure counts observable.
- Keep collection, JSON formatting, disk writes and the viewer outside gameplay's critical path. Loss of debug infrastructure must not stop gameplay.
- Provide reproducible one-to-four-controller workloads, trace replay and fault injection as explicit future deliverables.
- Correlate application records with independent packet and electrical evidence. A packet ACK is not a physics result; a motor command is not vibration onset.

This repository does not own physics, tracking, controller firmware or committed ball state. Their emitters must follow the [central interfaces](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md) and [debug architecture](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md).

## Current prerequisites and quick start

Git and Python 3.9 or later are sufficient for the supplied offline tools. No third-party Python packages, GPU, camera or connected controllers are required. The repository URL comes from the inspected Git remote:

```sh
git clone git@github.com:motion-tennis/debug-units.git
cd debug-units
python3 scripts/check_trace.py examples/synthetic-trace.jsonl
python3 -m unittest discover -s tests -v
```

SSH access must already be configured. On Windows, use the equivalent installed Python launcher, such as `py -3`, in place of `python3` if that is how Python is installed. These commands audit synthetic data and run local tests; there is no live-service launch command yet.

## Available smoke test and outputs

The example audit must report five started transactions from four controllers, three application results, one censored timeout, one local input drop, and no integrity errors. One completed response intentionally exceeds the provisional 30 ms target. All values are illustrative, not hardware measurements.

The JSON report includes median/p95/p99/observed maximum, target exceedances, explicit failure outcomes, source loss counters, per-controller metrics and eligible/suppressed/noneligible electrical cues. It never inserts a timeout as an invented completion latency. See [trace-v1](docs/trace-format.md) for fields, event semantics and limits.

## Planned runtime environment

The reference runtime collector is a separate process on the Windows RTX 5080 laptop. It receives bounded compact trace batches on reserved UDP port 41030; an operator/control API on reserved TCP 41043 is planned. These are proposed interface assignments, not running services. Live emitters should batch binary records within the protocol's 1,200-byte datagram ceiling and normalize them to JSONL off the critical path; do not send one verbose JSON object for every high-rate event.

The debug deployment also includes optional Pi/laptop pcapng capture with Wireshark tools and an independent logic analyzer for physical boundaries. Actual camera capture, pose inference, physics and game modules remain in their component repositories. Packet capture timestamps and application clocks require mapping before cross-device comparisons; no half-RTT assumption is valid.

The [implementation plan](docs/implementation-plan.md) assigns the remaining collector, decoder, viewer, replay, fault and acceptance work. The canonical [master plan](https://github.com/motion-tennis/documentation/blob/main/docs/master-plan.md) governs rates, payload bounds and device responsibilities.

## Repository layout

```text
README.md                       Role, actual commands and implementation status
LICENSE                         Existing MIT license
docs/trace-format.md            Normalized trace-v1 contract and audit semantics
docs/implementation-plan.md     Remaining runtime debug environment deliverables
scripts/check_trace.py          Runnable offline JSONL audit and metrics
examples/synthetic-trace.jsonl  Explicitly synthetic known-answer fixture
tests/test_trace_audit.py       Measurement-integrity regression tests
```

## Validation and limitations

Run the audit and tests above, plus `git diff --check`. Run the central documentation checker from the documentation checkout when updating shared interfaces. The tests cover failure accounting, wrong clocks, duplicate actuation, missing terminal records, late completion, trace gaps, duplicate JSON keys and empty runs.

The tool does not decode gameplay packets, collect live traces, validate complete batch/state-machine behavior, estimate clock mappings or prove hardware timing. A source that never logs anything cannot be discovered without a future run manifest/source registry; declare expected sources when collecting real trials. The current auditor loads one file into memory and is intended for bounded fixtures and exported runs, not unlimited live ingestion.

## Contribution and project links

All changes, code, comments, examples and documentation must be in English. New C/C++ comments use `//`. Preserve existing work and attribution; do not commit credentials or describe synthetic evidence as live measurements. Keep the trace contract compatible across all component emitters and label planned capabilities honestly.

- [Documentation](https://github.com/motion-tennis/documentation), [master plan](https://github.com/motion-tennis/documentation/blob/main/docs/master-plan.md), [timing](https://github.com/motion-tennis/documentation/blob/main/docs/timing.md), [testing](https://github.com/motion-tennis/documentation/blob/main/docs/testing.md).
- [Controller](https://github.com/motion-tennis/motion-tennis-controller), [camera tracking](https://github.com/motion-tennis/motion-tennis-camera-tracking), [physics](https://github.com/motion-tennis/motion-tennis-physics-engine), [game engine](https://github.com/motion-tennis/motion-tennis-game-engine).

Licensed under the [MIT License](LICENSE), copyright 2026 Motion Tennis Group. Preserve this notice.
