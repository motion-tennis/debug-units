# Debug repository orientation

[Repository home](../README.md) · [Local workflow](workflow.md) · [Contributor instructions](../AGENTS.md)

## Role and boundaries

`debug-units` preserves evidence for the complete controller -> Pi -> game -> Pi -> controller path, including camera-input provenance, required ball query/response, atomic commit, feedback and separate display/electrical observations. It supplies local audit tools now and will supply bounded collection, views and reproducible experiments at the appropriate [shared stages](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md).

The controller owns sensor capture and local feedback boundaries; tracking owns camera observations; physics owns fusion, clock mapping and candidate match calculations; the game service owns committed state. This repository consumes their evidence. It does not decide hits, advance scores, assign players or fit a competing authoritative clock timeline. Collection, formatting, storage and viewing must not block any gameplay component.

| Boundary | Current or planned artifact |
| --- | --- |
| Current input | One bounded normalized trace-v1 JSONL file, with a run header and original source event records |
| Current output | JSON audit/metrics report on standard output and a success/failure exit status |
| Planned source inputs | Bounded source exports, expected-source/run manifest, Pi-issued map/use/selection evidence, marker links and per-sample outcomes |
| Planned independent evidence | Packet captures and calibrated GPIO/optical/mechanical traces, each retaining its own clock and boundary meaning |
| Planned output | Run bundles, complete transaction/marker views, numeric timing uncertainty, replay evidence, fault/load trial reports and reproducible comparisons |

## What exists and what it proves

The actual implementation is [scripts/check_trace.py](../scripts/check_trace.py), [tests/test_trace_audit.py](../tests/test_trace_audit.py) and the [synthetic fixture](../examples/synthetic-trace.jsonl). It uses Python's standard library. The fixture is illustrative data, not a recorded hardware or multiplayer run.

The checker validates normalized JSONL/header/event structure, scalar/identity conventions, producer sequence uniqueness, timestamp monotonicity within a source clock and reported evidence gaps/loss. For started controller transactions it checks source/session/clock consistency, exactly one terminal outcome, expiry and electrical cue eligibility/identity/order, including duplicate or missing actuation/suppression. It reports same-controller response/electrical distributions, target exceedances, failure outcomes, censored timeouts and local drops. A discarded old response remains diagnostic rather than creating another completed transaction.

It does **not** decode Protobuf, validate mandatory pipeline-stage presence or full batch/commit behavior, correlate hardware markers, validate versioned clock maps or uncertainty, enforce doubles rules, collect live traffic or measure hardware. Arbitrary diagnostic event acceptance is not semantic validation. Missing entire producers require a future expected-source registry; the current file checker cannot discover a producer that emitted nothing. It loads a file into memory and is not an unlimited live ingestion service. Read [trace-v1](trace-format.md) before interpreting a passing report.

## Reading order and status authority

1. Read [AGENTS.md](../AGENTS.md), then the [central project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md). That file owns the current active stage and verified progress; local plans do not duplicate mutable stage status.
2. Read the [shared stages](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md), [contribution workflow and task/handoff template](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md), and this repository's [stage mapping](workflow.md).
3. Read [trace-v1](trace-format.md), the relevant [implementation work package](implementation-plan.md), and the current checker/tests before choosing an acceptance claim.
4. For shared changes, read the central [debugging design](https://github.com/motion-tennis/documentation/blob/main/docs/debugging.md), [clock contract](https://github.com/motion-tennis/documentation/blob/main/docs/coordinates-and-time.md#pi-reference-clock-mapping), [marker contract](https://github.com/motion-tennis/documentation/blob/main/docs/imu-trigger-markers.md) and [protocol](https://github.com/motion-tennis/documentation/blob/main/docs/protocol.md). Full-match work also needs [gameplay](https://github.com/motion-tennis/documentation/blob/main/docs/gameplay.md) and [player assignment](https://github.com/motion-tennis/documentation/blob/main/docs/player-assignment.md).

Prefer these central files in an available sibling checkout; record a verified revision/status reference in the task. A missing checkout or inaccessible status is not permission to guess progress. A pinned verified status plus explicit task evidence can provide the required context as described in the contributor instructions.

## Available checks

From this repository root, with Python 3.9 or later:

```sh
python3 scripts/check_trace.py examples/synthetic-trace.jsonl
python3 -m unittest discover -s tests -v
git diff --check
```

The supplied fixture should report five started transactions from four controllers, three application results, one censored timeout, one local drop and no integrity errors. One result deliberately exceeds the response target. Its small synthetic timing distribution is not a performance acceptance test.

When the sibling documentation checkout is available, check shared/local Markdown references with:

```sh
python3 ../documentation/scripts/check_docs.py
```

Inspect new untracked Markdown files for UTF-8, final newlines and trailing whitespace because `git diff --check` alone does not include them. No live collector/viewer/replay startup command exists. Documentation checks do not compile Protobuf or validate timing, sensor, renderer or match behavior.

## Bounded S0 tasks

Use the central status to confirm task eligibility. Suitable S0 slices are an evidence-backed inventory of current audit coverage; clarification of trace IDs, epoch/mapping references, marker linkage and loss semantics; and specifications of known-answer and rejection fixtures for the future full-match contract. Explicitly tasked small contract-validation tools/fixtures may support the central S0 gate; they do not authorize new runtime components. Record exact acceptance cases, coverage limits and later implementation stages in the central task/handoff format.

Keep the current offline audit reproducible while defining these contracts. S0 completion does not add a live collector or viewer and does not turn planned marker/map/match checks into implemented coverage. Extending offline conformance belongs to S1; isolated live evidence begins at S2, and the integrated one-controller viewer belongs to S3. Consult the [workflow](workflow.md) before expanding a task.
