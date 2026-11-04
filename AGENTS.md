# Debug repository contributor instructions

These instructions apply to this repository and its subdirectories, for human and AI contributions.

## Git branch and remote workflow

Follow the [shared Git workflow](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md#git-branch-and-remote-workflow) for every task.

- Before any file edit, verify the repository, current branch and working-tree status. Work on a dedicated branch for this task, never on `main`, detached HEAD or another task's branch. Preserve existing work; use a separate worktree when needed rather than resetting, discarding or automatically stashing it.
- Fetch before starting and create new task branches from the freshly fetched `origin/main` with `--no-track`; verify the remote/default branch first. If fetching fails, record the failure and known base revision before continuing local work on a task branch. Remote freshness remains unverified, and pushing must wait for a successful fetch and synchronization.
- Before every authorized push, run `git fetch --prune origin`, review changes to `origin/main` since the previous synchronization, and integrate the latest main and any new commits on the remote task branch into the task branch.
- Prefer merges to preserve published history. Resolve conflicts while preserving both contributors' intent; ask only when the intended resolution is ambiguous. Rerun relevant checks after integration and require `origin/main` and the existing remote task branch to be ancestors of `HEAD` before pushing.
- Push explicitly to the intended remote task branch. If the remote advances or rejects a push, fetch, integrate, resolve conflicts and revalidate before retrying. Do not force-push, rewrite shared history or push directly to `main` without explicit authorization for that action.
- Branch preparation and synchronization do not authorize committing or publishing. Honor existing user authorization without asking for it again; otherwise leave the reviewed changes local and report the branch, checks and any synchronization limits.

## Contribution rules

1. Before changing code, read [orientation](docs/orientation.md), [workflow](docs/workflow.md), the [central project status](https://github.com/motion-tennis/documentation/blob/main/docs/project-status.md), [stage gates](https://github.com/motion-tennis/documentation/blob/main/docs/project-stages.md) and [contribution workflow](https://github.com/motion-tennis/documentation/blob/main/docs/contribution-workflow.md). Prefer the corresponding files in an available sibling `documentation` checkout and record the revision used. Inspect local Git status and relevant source/tests; preserve existing work.
2. Name one stage and a bounded task with acceptance evidence before implementation. The central status is the authority for the active stage; this repository has no independent stage progression. A passing local test or finished task does not advance the project or authorize later-stage work.
3. A direct human instruction naming a bounded slice of a future stage can authorize that slice. Record the instruction, stage, scope, unmet dependencies and remaining gates in the handoff; it does not advance the global stage or authorize neighboring work. Proceed with already authorized routine checks and fixes without requesting redundant approval.
4. If central status cannot be read, use a verified pinned status revision and explicit task evidence when available. Do not infer a stage from dates, file presence or a passing audit. Without reliable status/task evidence, recover that context before dependent implementation; report the missing evidence rather than guessing.
5. Keep repository content in English, including examples and comments; new C/C++ comments use `//`. Preserve licenses, attribution and unrelated changes. Use the central task/handoff template rather than creating a competing status log.
6. Preserve gameplay contracts and debug noninterference: bounded asynchronous export, unchanged continuous controller stream, diagnostic-only markers, complete transaction identities/outcomes and no collector/viewer dependency in gameplay. The Pi owns clock mappings; retain raw clocks, version/epoch provenance, uncertainty and explicit evidence gaps. Debug does not become a scorer, clock authority or physics writer.
7. Label implemented, agreed, proposed and unverified behavior accurately. The existing auditor covers local measurement integrity; it does not establish wire, map/marker, full-match or hardware correctness. New coverage needs implementation and meaningful fixtures before claims change.
8. Use the real checks in [orientation](docs/orientation.md#available-checks). Run checks relevant to the change, report exact results and limits, and hand off remaining work under the named stage. Do not invent runtime commands, measurements or gate completion.
