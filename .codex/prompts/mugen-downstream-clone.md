# muGen Downstream Clone Prompt

Use this prompt to create a new downstream application repository from
`vorsocom/mugen` while keeping upstream merges clean.

```text
Clone muGen as a downstream application with a merge-clean downstream release
workflow.

Suggested chat title: muGen Downstream Clone - <APP_SLUG>

Inputs:
- Downstream app display name: <APP_NAME>
- App slug: <APP_SLUG>, using lowercase letters, digits, and hyphens only
- If an app slug is required and the user did not explicitly provide one,
  default `<APP_SLUG>` to the GitHub repository name from the downstream origin
  URL.
- Local directory: <LOCAL_DIR>
- Downstream origin URL: <ORIGIN_URL>
- Downstream author: <AUTHOR>
- Downstream contact email: <EMAIL>
- Initial downstream app version: 0.0.0 unless otherwise specified
- Optional downstream Python requirements file path, defaulting to
  `requirements-downstream.txt` when the downstream app has extra dependencies
- Optional engineering spec attachment describing downstream app layout,
  package names, extension points, migration tracks, deployment expectations, or
  product-specific constraints

Preflight requirements:
1. Verify the target local directory does not exist unless the user explicitly
   asks to reuse an existing directory.
2. Verify upstream `main` is reachable with:
   `git ls-remote --heads git@github.com:vorsocom/mugen.git main`.
3. Verify the downstream origin URL is reachable and empty, or stop if it
   already contains branches/tags unless the user explicitly confirms reuse.
4. Verify `gh` authentication before attempting GitHub repository edits such as
   setting the default branch.
5. If a GitHub repository identifier is supplied or derived for `gh` commands,
   verify it matches the downstream origin URL before making repository edits.

Clone/setup requirements:
1. Clone `git@github.com:vorsocom/mugen.git` into the local directory.
2. Name the upstream remote `upstream`.
3. Clone only upstream `main`, with full history, single branch, and no tags.
4. Configure future upstream fetches to fetch only `main` and no tags:
   - `remote.upstream.tagOpt = --no-tags`
   - upstream fetch refspec includes only `refs/heads/main`
5. Disable pushes to upstream by setting the upstream push URL to
   `PUSH_DISABLED`.
6. Add the downstream repository as `origin`.
7. Push `main` to `origin/main`.
8. Create `develop` from the cloned `main`, push it to `origin/develop`, and
   make local `develop` track `origin/develop`.
9. Set the downstream GitHub default branch to `develop` if `gh` is
   authenticated and authorized.
10. Create root `downstream.toml` using `conf/downstream.toml.sample`
    semantics:
    - `schema_version = 1`
    - `[app].name`, `author`, `copyright`, `email`, `version`
    - `[app].version = "0.0.0"` unless another initial downstream app version
      is specified
    - `[upstream].repo = "vorsocom/mugen"`
    - `[upstream].branch = "main"`
    - `[upstream].sync_ref` = exact cloned upstream `main` commit
    - `[upstream].sync_tag` only if that exact commit corresponds to an
      upstream tag, checked remotely without fetching local tags
11. Keep `downstream.toml` limited to provenance and downstream app metadata.
    Do not store runtime settings, secrets, local paths, or machine-specific
    values in it.
12. If a later upstream sync moves to an untagged commit, remove any stale
    `upstream.sync_tag` while preserving the exact `upstream.sync_ref`.
13. Commit `downstream.toml` as
    `chore(downstream): initialize provenance` and push to `origin/develop`
    unless explicitly told not to commit.

Downstream artifact layout:
- Create `downstream/README.md` during clone setup.
- Prefer `downstream/` for downstream-owned deployment templates, operator
  documentation, overlays, examples, and app-specific artifacts.
- Recommended subdirectories:
  - `downstream/aws/` for AWS deployment templates and examples.
  - `downstream/docs/` for downstream operator and deployment notes.
- Keep files in fixed tool locations only when required, such as GitHub Actions
  workflows under `.github/workflows`.
- Name fixed-location downstream files distinctly, for example
  `.github/workflows/deploy-<APP_SLUG>-ecs.yml`.

Upstream tag detection:
1. Determine `sync_ref` from the cloned upstream `main` commit.
2. Inspect remote tags without importing them locally:
   `git ls-remote --tags git@github.com:vorsocom/mugen.git`.
3. Treat `refs/tags/<tag>` as a lightweight tag candidate and
   `refs/tags/<tag>^{}` as the peeled commit for an annotated tag.
4. If exactly one remote tag candidate resolves to `sync_ref`, record that tag
   in `upstream.sync_tag`.
5. If no remote tag resolves to `sync_ref`, omit `upstream.sync_tag`; on later
   upstream syncs, remove any stale `upstream.sync_tag`.
6. If multiple remote tags resolve to the same `sync_ref`, stop and ask which
   tag should be recorded instead of guessing.
7. Do not run `git fetch --tags` or `git push --tags` during this process.

Downstream Python requirements:
1. Do not add downstream-only dependencies to upstream `pyproject.toml` unless
   the user explicitly chooses to fork the upstream dependency graph.
2. If the downstream app has extra Python dependencies, record them in a
   downstream-owned requirements file such as `requirements-downstream.txt`.
   Create this file only when extra dependencies exist; do not add an empty
   placeholder file.
3. Keep the requirements file deterministic enough for deployment. Prefer pinned
   versions for application/runtime dependencies.
4. Poetry does not read this file during `poetry install`; for local
   development, install upstream dependencies with Poetry, then install
   downstream requirements into the same environment with:
   `poetry run pip install -r requirements-downstream.txt`.
5. After installing downstream requirements, run `poetry run pip check` or the
   equivalent container check to catch dependency conflicts with upstream muGen.
6. Install downstream requirements only in downstream-owned setup surfaces, such
   as a downstream Dockerfile, local bootstrap script, or deployment workflow.
7. A downstream Dockerfile should install upstream muGen first, then downstream
   requirements, then the downstream app package or source tree. For example:
   `pip install --no-cache-dir -r requirements-downstream.txt`.
8. If downstream tests require downstream-only dependencies, add a
   downstream-owned CI step or workflow that installs
   `requirements-downstream.txt`; do not modify upstream-owned test/release
   workflows unless the user accepts that downstream fork.
9. Do not store downstream runtime extension registration in the requirements
   file; use `MUGEN_EXTENSIONS_JSON`, `MUGEN_MIGRATION_TRACKS_JSON`, config
   overlays, or downstream-owned runtime config for that.

Downstream deployment fork policy:
- If a downstream app intentionally forks upstream deployment behavior, put the
  downstream source of truth in downstream-specific files.
- Keep generic upstream deployment files present for upstream synchronization
  context unless explicitly removed.
- Do not make generic upstream deployment workflows the downstream production
  source of truth.
- If a generic upstream deployment workflow remains and could deploy
  infrastructure, guard it so it cannot deploy from the downstream repository.
- When upstream changes deployment behavior on `upstream/main`, review those
  changes and port relevant behavior into downstream workflow, templates, and
  docs.

Downstream release workflow:
1. Downstream app versions are independent from upstream muGen versions.
2. Do not run upstream `scripts/release.py` for downstream releases; it edits
   upstream-owned version files.
3. Keep `pyproject.toml`, `quartman.py`, README badges, upstream release
   scripts, and upstream workflows pinned to upstream.
4. Do not add downstream provenance or downstream release metadata to
   `pyproject.toml`; use `downstream.toml` instead.
5. Start each release from fresh `origin/develop`.
6. Validate that the release version is exactly `X.Y.Z`, using numeric SemVer
   core components with no prefix or suffix.
7. Validate that the release branch is exactly
   `release/<APP_SLUG>-vX.Y.Z`.
8. Reject bare upstream-style tags such as `vX.Y.Z`, tags without the app slug,
   branches with spaces, or names containing local usernames or sensitive
   customer details.
9. Update only `[app].version` in `downstream.toml`.
10. Commit as `chore(release): <APP_SLUG>-vX.Y.Z`.
11. Open a PR from `release/<APP_SLUG>-vX.Y.Z` to `main`.
12. PR descriptions must not include absolute paths, usernames, interpreter
    paths, machine-specific commands, secrets, local repo names, private
    customer names unless the downstream repo is explicitly scoped to that
    customer, or raw environment variable values.
13. After merge, resolve the merged `origin/main` commit and create annotated
    tag `<APP_SLUG>-vX.Y.Z` at that commit.
14. Push only the explicit downstream tag; never run `git push --tags`.
15. Sync the merged `origin/main` release commit back into `develop`, then
    delete the release branch.

Upstream sync workflow:
1. Fetch upstream only with `git fetch upstream main --no-tags`.
2. Merge `upstream/main` into `develop`.
3. Update only the `[upstream]` fields in `downstream.toml`.
4. Do not fetch or import upstream tags locally.
5. If the new `upstream.sync_ref` corresponds to an upstream tag, set
   `upstream.sync_tag`; otherwise remove any stale `upstream.sync_tag`.
6. Push the updated `develop` to `origin/develop`.

Upstream merge conflict policy:
- For upstream-owned files, generally take upstream changes unless the user
  intentionally requested a downstream-owned fork of that behavior. This includes
  `pyproject.toml`, `quartman.py`, README badges, `scripts/release.py`,
  upstream workflows, and `mugen/core`.
- For downstream-owned files, preserve downstream changes while still updating
  upstream provenance. This includes `downstream.toml`, the downstream app
  package, downstream requirements file, downstream deployment overlays,
  downstream docs, and downstream runtime configuration.
- If an engineering spec conflicts with the upstream/downstream boundary rules,
  stop and report the conflict instead of implementing around it.

Architecture guidelines:
- If an engineering spec is supplied as an attachment, read it before creating
  downstream files and use it as the source of truth for downstream app layout.
- Engineering specs may define downstream layout and ownership, but they must
  not override the upstream/downstream boundary rules.
- Do not add downstream business logic under `mugen/core`.
- Put downstream app code in a top-level downstream package.
- Use supported extension/config seams and plugin-owned migration tracks.
- Treat ACP resources/actions and documented collaborator seams as the extension
  boundary.
- During clone/setup, do not implement downstream product logic from the spec
  unless explicitly requested; record or scaffold only the setup artifacts the
  clone task asks for.

Verification:
- Verify `upstream` fetches `git@github.com:vorsocom/mugen.git`.
- Verify `upstream` push is `PUSH_DISABLED`.
- Verify `origin` points to the downstream repository.
- Verify the upstream fetch refspec only includes `refs/heads/main`.
- Verify `remote.upstream.tagOpt` is `--no-tags`.
- Verify `git tag --list` is empty after clone setup.
- Verify local `develop` tracks `origin/develop`.
- Verify local `main` tracks `origin/main`.
- Verify the downstream GitHub default branch is `develop`.
- Verify `downstream.toml` parses and contains required `[app]` and
  `[upstream]` metadata.
  Run a parse check such as:
  `python3 - <<'PY'`
  `import tomllib`
  `from pathlib import Path`
  `data = tomllib.loads(Path("downstream.toml").read_text())`
  `assert data.get("schema_version") == 1`
  `for key in ("name", "author", "copyright", "email", "version"):`
  `    assert key in data["app"]`
  `for key in ("repo", "branch", "sync_ref"):`
  `    assert key in data["upstream"]`
  `PY`
- Dry-check that the downstream release-prep commit would modify only
  `downstream.toml`.
```

Important release policy:

- Downstream app release versions are independent from upstream muGen versions.
- Use app-prefixed downstream tags to avoid collisions with upstream tags.
- Prioritize low-conflict upstream merges over local release automation changes.
- Add future downstream release automation as separate downstream-owned files,
  not by modifying upstream release scripts or workflows.
- Name downstream automation distinctly, for example
  `.github/workflows/downstream-release.yml`, to avoid confusing it with
  upstream workflows.
