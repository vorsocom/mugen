# muGen Downstream Work Session Prompt

Use this prompt at the start of an agent session inside an existing downstream
muGen repository. It is standing policy only until a later concrete task is
given.

```text
Treat this message as standing policy/context only, not as a task to execute now.

Suggested chat title: muGen Downstream Work Session - <GH_REPO>

Startup behavior:
- Do not run commands, checks, git/gh actions, or file edits from this message
  alone.
- First response must be a brief confirmation that you understand and will
  follow these rules.
- After confirming, wait for a later explicit task.
- Apply the workflow below only when a later concrete task is given.

Placeholder replacement check:
- Before using this prompt for an actual downstream repo, replace all required
  placeholders: `<DOWNSTREAM_REPO_PATH>`, `<ORIGIN_URL>`, `<GH_REPO>`,
  `<PYTHON_INTERPRETER>`, `<DOWNSTREAM_EDIT_SCOPE>`, and `<COMMIT_POLICY>`.
- `<COMMIT_POLICY>` must be either `auto-after-gates` or
  `ask-before-commit`.
- If any required placeholder remains when a concrete task starts, stop and ask
  for the missing value instead of guessing.

Workspace:
- Repository: <DOWNSTREAM_REPO_PATH>
- Writable remote: `origin` (<ORIGIN_URL>)
- GitHub repository for `gh -R`: <GH_REPO>, for example `vorsocom/app-repo`
- Read-only upstream remote may exist as `upstream`; never push to `upstream`.
- Base branch: `develop`
- Release branch: `main`
- Use this Python interpreter for all commands: <PYTHON_INTERPRETER>
- If that interpreter path is missing or unusable, stop and report it instead of
  silently switching to a different Python.
- Downstream-owned edit scope: <DOWNSTREAM_EDIT_SCOPE>
- Do not modify files outside the downstream-owned edit scope unless the task
  explicitly requires a downstream-owned config, docs, migration, deployment, or
  provenance change.
- Commit policy: <COMMIT_POLICY>
- Treat `mugen/core`, upstream release scripts, upstream workflows,
  `pyproject.toml`, `poetry.lock`, `quartman.py`, and upstream README
  version/badge behavior as upstream-owned unless the user explicitly chooses to
  fork that behavior.
- Prefer `downstream/` for downstream-owned deployment templates, operator docs,
  overlays, examples, and app-specific artifacts.
- Keep fixed-location tool files only where required, such as workflows under
  `.github/workflows`.
- Name downstream fixed-location files distinctly, for example
  `deploy-<app-slug>-ecs.yml`.
- Treat generic upstream deployment workflows and templates as upstream-owned
  unless the user explicitly forks deployment behavior.
- When deployment behavior is forked, create downstream-specific workflow,
  template, and docs; keep generic upstream files unchanged or guarded.

Task startup checks:
- Verify current directory is `<DOWNSTREAM_REPO_PATH>`.
- Verify `origin/develop` exists. If it does not, stop and report that the
  downstream base branch is missing; do not substitute another base branch.
- Verify the configured `origin` URL matches `<ORIGIN_URL>`.
- Verify `<GH_REPO>` is the GitHub owner/repository behind `<ORIGIN_URL>` before
  running any `gh -R <GH_REPO>` or `gh api repos/<GH_REPO>/...` command.
  If they disagree, stop and report the mismatch.
- Verify `upstream`, if present, has push URL `PUSH_DISABLED` or otherwise is
  not writable.
- Verify `gh --version` and `gh auth status`.
- If GitHub auth is missing or invalid, stop and report this exact next command:
  `gh auth login -h github.com --insecure-storage`.
- Use `gh -R <GH_REPO>` for PR creation, inspection, monitoring, and merge.
- For `gh api`, use explicit `repos/<GH_REPO>/...` endpoints because `gh api`
  does not accept `-R`.
- Do not rely on default GitHub repo resolution.

`mugen.toml` protection:
- `mugen.toml` is persistent local runtime config and may contain
  non-recoverable local values/secrets.
- It is modeled after `conf/mugen.toml.sample`, but it is not disposable.
- Only make structural/schema-alignment changes to `mugen.toml`; preserve all
  existing runtime values.
- Never overwrite `mugen.toml` wholesale from `conf/mugen.toml.sample`.
- Never run generators/scripts that write directly to `mugen.toml` unless the
  user explicitly instructs that exact action.
- Before editing `mugen.toml`, create `_dev/bak` if needed and write a
  timestamped backup such as `_dev/bak/mugen.toml.pre-edit-<timestamp>.bak`.
- Treat `_dev/bak` backups as local safety artifacts. Do not commit them unless
  the user explicitly requests that exact backup artifact to be committed.
- When updating schema, start from the current `mugen.toml`, add missing keys,
  and remove obsolete keys only if current code requires it.
- After editing `mugen.toml`, report keys structurally added, removed, or
  relocated; confirm non-structural values were preserved; and name the backup
  file.

`downstream.toml` protection:
- `downstream.toml` is project-root downstream provenance metadata and may exist
  only locally.
- It is modeled after `conf/downstream.toml.sample`, but it is not disposable.
- Keep runtime settings, secrets, local paths, and machine-specific values out of
  `downstream.toml`.
- Only edit `downstream.toml` when the task explicitly requires downstream
  provenance, upstream sync metadata, or downstream app metadata changes.
- Never overwrite `downstream.toml` wholesale from `conf/downstream.toml.sample`.
- Before editing `downstream.toml`, create `_dev/bak` if needed and write a
  timestamped backup such as
  `_dev/bak/downstream.toml.pre-edit-<timestamp>.bak`.
- Treat `_dev/bak` backups as local safety artifacts. Do not commit them unless
  the user explicitly requests that exact backup artifact to be committed.
- After editing `downstream.toml`, report keys structurally added, removed, or
  relocated; confirm unrelated values were preserved; and name the backup file.
- After editing `downstream.toml`, validate it with a tomllib parse check such
  as:
  `<PYTHON_INTERPRETER> - <<'PY'`
  `import tomllib`
  `from pathlib import Path`
  `data = tomllib.loads(Path("downstream.toml").read_text())`
  `assert data.get("schema_version") == 1`
  `for key in ("name", "author", "copyright", "email", "version"):`
  `    assert key in data["app"]`
  `for key in ("repo", "branch", "sync_ref"):`
  `    assert key in data["upstream"]`
  `PY`

Downstream Python requirements:
- Downstream-only Python dependencies belong in a downstream-owned requirements
  file such as `requirements-downstream.txt`, not upstream `pyproject.toml`,
  unless the user explicitly chooses to fork the upstream dependency graph.
- For local development, install upstream dependencies with Poetry, then install
  downstream requirements into the same environment with
  `<PYTHON_INTERPRETER> -m pip install -r requirements-downstream.txt` or
  `poetry run pip install -r requirements-downstream.txt`.
- Run `<PYTHON_INTERPRETER> -m pip check` after installing downstream
  requirements.

Git workflow:
- Always start work from fresh `origin/develop`.
- Never commit directly to `develop` or `main`.
- Create a feature branch for the task, such as `fix/<topic>`,
  `feat/<topic>`, `docs/<topic>`, or `chore/<topic>`.
- Branch names must be lowercase and hyphenated, with no spaces, local
  usernames, absolute paths, raw issue text containing sensitive details, or
  private customer names unless the downstream repo is explicitly scoped to that
  customer.
- Push feature branches to `origin` only.
- If `<COMMIT_POLICY>` is `auto-after-gates`, then after implementing the task
  and passing quality gates, create the commit, push the branch, open the PR,
  monitor GitHub to completion, merge when allowed, and perform post-merge
  cleanup without asking for separate commit approval.
- If `<COMMIT_POLICY>` is `ask-before-commit`, then after implementing the task
  and passing quality gates, stop and ask for explicit commit approval. Once the
  user approves the commit, complete the commit, push, PR, monitoring, merge,
  and cleanup workflow without asking again.
- Stop before committing if quality gates, repo policy, mergeability, or
  required review status blocks completion.

Conventional commit enforcement:
- The git commit subject, PR title, and merge-commit subject must all use
  conventional commit format.
- Allowed forms:
  - `<type>: <description>`
  - `<type>(<scope>): <description>`
  - `<type>!: <description>`
  - `<type>(<scope>)!: <description>`
- Allowed types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`,
  `ci`, `chore`, `revert`.
- The description must be concise, imperative, and must not end with a period.
- Validate this format before `git commit`, before `gh pr create`, and before
  `gh pr merge --merge`.
- If any subject/title is invalid, correct it before proceeding.

Quality gates before commit or push:
- Run:
  `bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh --python <PYTHON_INTERPRETER>`
- Explicitly confirm:
  - complete test suite passed
  - complete E2E validation passed
  - coverage is still 100%
- If the repo has downstream-only requirements, make sure they are installed
  before running gates.
- If quality gates fail, do not commit or push. Report the failure and the next
  debugging options.

Downstream deployment sync:
- Downstream deployment files are not automatically updated when upstream
  changes generic deployment behavior.
- When syncing from `upstream/main`, review workflow, action input, task
  template, migration/reseed, smoke-test, and env/secret contract changes.
- Port relevant changes into downstream-specific deployment files and docs.
- Do not assume upstream generic deployment files are the downstream production
  source of truth.

GitHub Actions troubleshooting:
- If a check fails but normal logs do not show the cause, inspect check-run
  annotations:
  `gh api repos/<GH_REPO>/check-runs/<CHECK_RUN_ID>/annotations`
- Always pass explicit repo for logs:
  `gh run view -R <GH_REPO> <RUN_ID> --job <JOB_ID> --log-failed`
- If a hosted runner reports `No space left on device`, treat it as CI resource
  pressure first.
- Full muGen dev dependency installs may need pre-install disk cleanup and
  reduced cache scope.
- Avoid caching `~/.cache/pip` in heavyweight test jobs unless measured safe.

Downstream release tasks:
- Validate that downstream release versions use numeric SemVer core form
  `X.Y.Z` before creating a release branch or tag.
- Validate that release branches use `release/{app-slug}-vX.Y.Z` and release
  tags use `{app-slug}-vX.Y.Z`, where `{app-slug}` is the downstream app slug.
- Reject bare upstream-style tags such as `vX.Y.Z`, tags without the app slug,
  branches with spaces, or names containing local usernames or sensitive
  customer details.
- Tag only the merged `origin/main` commit and push only the explicit downstream
  release tag. Never run `git push --tags`.

PR creation and monitoring:
- After push, create the PR with `gh pr create -R <GH_REPO>` targeting
  `develop`.
- Provide the PR URL.
- PR descriptions must not include absolute paths, usernames, interpreter paths,
  machine-specific commands, secrets, local repo names, private customer names
  unless the downstream repo is explicitly scoped to that customer, or raw
  environment variable values.
- After PR creation, monitor GitHub status with `gh pr view -R <GH_REPO>` and/or
  `gh pr checks -R <GH_REPO>`.
- Poll every 30 seconds for up to 30 minutes from PR creation.
- During monitoring, report only meaningful status changes.
- Continue automatically while checks are pending and no human action is
  required.
- Stop and report immediately if any required check fails, required review or
  approval is missing, merge conflicts exist, branch protection or repo policy
  blocks merge, `gh` cannot determine status reliably, or the 30-minute timeout
  is reached.
- If timeout occurs, report the latest PR state, outstanding blockers, and exact
  next `gh` commands to continue later.
- If the PR becomes mergeable within the monitoring window, generate and report
  the conventional merge-commit message, then merge automatically with:
  `gh pr merge -R <GH_REPO> <PR_URL_OR_NUMBER> --merge --delete-branch=false --subject "<MERGE_SUBJECT>" --body ""`
- After merge, report the merged PR URL and resulting commit SHA if available.

Reporting requirements:
- Show exactly what changed, with files and purpose.
- Summarize key quality-gate results.
- Include key git/gh results: branch, commit, push, PR creation, PR monitoring
  outcome, merge result, and cleanup result.
- If blocked, stop and report the blocker with next action options.

Post-merge cleanup:
1. `git checkout develop`
2. `git pull --ff-only origin develop`
3. `git update-ref -d refs/heads/<feature-branch>`
4. Delete the remote feature branch with:
   `gh api repos/<GH_REPO>/git/refs/heads/<feature-branch-url-encoded> --method DELETE`
   Example: `fix/keyval-dbm-hardening` becomes
   `fix%2Fkeyval-dbm-hardening`.
5. If the remote branch is already absent, report it as already cleaned up.
6. Confirm final state with:
   - `git status --short`
   - `git branch --show-current`
   - `git rev-parse --short HEAD`
```

Before using this prompt, replace all placeholders with downstream-specific
values. If the downstream repo has stricter branch protection that prevents
automated merge, keep the automated monitoring behavior and report the policy
blocker as the completion boundary.
