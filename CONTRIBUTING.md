## Contributor License Agreement

Contributing code to muGen requires a developer to sign the
[<u>**Contributor License Agreement**</u>](CLA.md).

## Commit Message Convention

muGen enforces Conventional Commits for:

1. Pull request titles.
2. Commit messages in pull requests.
3. Commits pushed directly to protected branches.

Expected format:

`<type>(<scope>): <description>`

Notes:

1. `scope` is optional.
2. `!` is allowed for breaking changes, e.g. `feat(api)!: remove legacy route`.
3. Merge and Git-generated revert commit subjects are allowed.

Allowed types:

`build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, `test`

## Local Hook Setup

Install the commit message hook locally:

```bash
poetry run pre-commit install --hook-type commit-msg
```
