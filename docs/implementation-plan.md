# Runtime debug environment implementation plan

[Repository home](../README.md) · [Trace contract](trace-format.md) · [Central debug specification](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md)

Only the offline auditor and its fixtures/tests exist. The modules below are planned entry points, not executable names or available commands. Implement them in this order and update the README with real commands when they exist.

| Deliverable | Host and responsibility | Acceptance evidence |
| --- | --- | --- |
| Source trace adapters | ESP32 firmware, Pi physics, Windows tracking/game; compact preallocated records at actual event boundaries | Bounded writes; original source clocks preserved; measured overhead; every started request represented or loss counted |
| Collector | Separate Windows Python process; bounded UDP trace-batch receiver on reference port 41030 | Protocol/version checks, source registry, event-sequence tracking, bounded queues, asynchronous JSONL writing, no blocking of gameplay |
| Run controller | Windows operator API, reference TCP 41043; builds manifests and starts/stops only explicitly selected test runs | Records exact revisions/profiles/hardware, seeds, source readiness, clock mappings and output paths; never starts network fault injection implicitly |
| Packet decoder | Wireshark/TShark-compatible analysis of the canonical gameplay wire envelope | Identifies controller/session/request, batch/query/update, message type and state version from fixtures; reports undecodable/version-mismatched packets |
| Timeline viewer | Local Windows UI reading collector output or completed bundles | Four controller lanes, per-transaction waterfall, stage uncertainty, selected pose/frame, failure/timeout/queue/state-lag views; paused viewer cannot block collection |
| Simulators and stubs | Desktop test processes emulating four controllers, tracking frames and game snapshot/commit service | Deterministic seeds; preserved per-transaction query/response even in batches; hit/miss/invalid/timeout/duplicate cases |
| Replay/fault harness | Test-only transport adapters; explicit opt-in execution | Seeded delay/jitter/loss/duplicate/reorder/corruption/restart per message boundary; fault log distinguishes injection from native loss |
| Protocol-aware auditor | Offline extension of the local auditor | Detects missing logical ball queries, uncommitted positive feedback, duplicate state application, old epochs, false freshness and incomplete source manifests |
| Hardware trace import | Offline logic-analyzer/photodiode/vibration traces joined using calibrated markers | Known units and clock transforms, declared thresholds and uncertainty, no inference of physical output from software alone |

Python is the reference orchestration/analysis language. Critical emitters use each component's implementation language and do not depend on Python in interrupt/tick paths. The viewer technology and pinned tool versions must be selected and recorded with the first runtime implementation; an initial offline HTML timeline is sufficient if it exposes the required evidence. A database or cloud dashboard is not required for the first milestone.

## Storage and process isolation

Each source uses a bounded ring and a lower-priority exporter. The collector uses separate receive, storage and view/update stages with finite queues and counters. Retain loss counts when storage or the viewer falls behind. Disk saturation must degrade observation, not block feedback. Use append-only per-source logs and a manifest; produce merged reports offline. Declare storage caps before enabling image/packet recording.

Raw live trace datagrams obey the central 1,200-byte limit. JSONL is the offline normalized representation, not the proposed high-rate wire encoding. Instrumentation verbosity, sampling of optional diagnostic payloads and raw-frame capture are run parameters. Never sample away started/terminal transaction accounting without preserving counters and explicitly marking the trace incomplete.

## Controlled experiment sequence

1. Run the supplied synthetic audit and integrity tests.
2. Add source emitters and collector; compare one controller's event ledger against the local counters and GPIO trace.
3. Run simulated input at the reference 200 Hz per controller, first one then four controllers; observe all 800 logical transactions per second and their batched state operations.
4. Inject loss/duplicate/timeout/conflict cases and verify that every attempt has a response or counted local failure.
5. Add real camera inference and render load on the Windows laptop; report their separate resource and latency effects.
6. Add real controllers and Pi 3B; measure rather than assume the 5 ms batching target, 30 ms response p99, 40 ms eligible-feedback p99 and 50 ms expiry behavior.
7. Compare instrumentation levels using external timing markers. Archive the full run evidence before accepting a performance claim.

The first full acceptance run must exercise one through four players, valid hits/misses, occlusion and identity crossings, stale frames/ball snapshots, simultaneous inputs, CPU/render load, network delay/jitter/loss/duplicates/reordering, queue overflow and every service restart. Retain completion distributions alongside timeouts, invalid tracking, admission drops, target exceedances and logging loss. Hardware/driver/runtime limits remain empirical until a bounded platform and workload have been verified.
