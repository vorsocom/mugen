# ChromaDB Dependabot remediation

Recorded on 2026-09-05. This change removes the vulnerable `chromadb==0.6.3`
distribution from muGen while retaining the Chroma knowledge gateway's remote
collection operations. GitHub alert closure remains pending merge into the default
`develop` branch and dependency reanalysis.

## Alerts and upstream status

The six open alerts represent three advisories reported against both dependency
files:

| Advisory | Severity | `pyproject.toml` alert | `poetry.lock` alert |
| --- | --- | --- | --- |
| [CVE-2026-45833 / GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf): code injection through collection embedding configuration | Critical | [#139](https://github.com/vorsocom/mugen/security/dependabot/139) | [#136](https://github.com/vorsocom/mugen/security/dependabot/136) |
| [CVE-2026-45831 / GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr): RBAC ignores resource scope | High | [#138](https://github.com/vorsocom/mugen/security/dependabot/138) | [#134](https://github.com/vorsocom/mugen/security/dependabot/134) |
| [CVE-2026-45830 / GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr): cross-tenant collection access | High | [#137](https://github.com/vorsocom/mugen/security/dependabot/137) | [#135](https://github.com/vorsocom/mugen/security/dependabot/135) |

All three advisories list no patched version. The latest official
[PyPI distribution](https://pypi.org/project/chromadb/1.5.9/) and
[upstream release](https://github.com/chroma-core/chroma/releases/tag/1.5.9) are
version 1.5.9, which remains inside the affected ranges. The proposed Python
authorization fix in [upstream PR #7602](https://github.com/chroma-core/chroma/pull/7602)
is still open and unmerged as of this review. Upgrading to that release would not
resolve these alerts.

The official `chromadb-client` wheels for
[0.6.3](https://pypi.org/project/chromadb-client/0.6.3/) and
[1.5.9](https://pypi.org/project/chromadb-client/1.5.9/) were also inspected. Both
still package the Python server, `SimpleRBACAuthorizationProvider`, segment API,
and database lookup code implicated in these advisories. The thin-client flag
restricts supported runtime modes but does not remove that source. Changing only
the distribution name would therefore leave vulnerable source in the application
installation.

## Replacement and compatibility

- Remove the direct `chromadb==0.6.3` dependency and its unused transitive
  dependencies from `pyproject.toml` and `poetry.lock`.
- Declare `httpx` directly with a `^0.28.1` constraint, retaining its existing
  locked and installed version 0.28.1, and use it for the gateway's HTTP transport.
- Retain collection lookup, query, upsert, and delete through tenant- and
  database-scoped API V2 paths. The former 0.6.3 SDK already defaults to API V2;
  see its [configuration](https://github.com/chroma-core/chroma/blob/0.6.3/chromadb/config.py)
  and [HTTP implementation](https://github.com/chroma-core/chroma/blob/0.6.3/chromadb/api/fastapi.py).
- Retain local embedding generation with `trust_remote_code=False`, existing
  gateway filters, and configured connection settings.

The lockfile decreases from **208 to 167 package entries**, removing **41**,
including ChromaDB. No package entries are added and no retained package versions
change. These are lockfile entry counts, including separate Torch variants, rather
than an inventory of one installed platform.

This removes the vulnerable Python distribution from muGen. It does not update or
remediate an independently deployed Chroma server. Its server version, access
controls, and remediation remain a separate deployment concern.

## Restoring the official SDK

This dependency replacement is reversible. ChromaDB remains a supported remote
backend, and the gateway's public contract and configuration remain in place.
Reconsider the official SDK when a released version fixes all three advisories,
or an official client distribution excludes the affected components. Verify the
upstream fixes, actual package contents, and dependency advisories; a different
package name or a newer version number alone is insufficient.

To restore it:

1. Add the verified dependency version and regenerate the Poetry lockfile.
2. Replace the adapter behind `ChromaKnowledgeGateway._create_http_client` in
   `mugen/core/gateway/knowledge/chromadb.py`, adapting SDK configuration as needed.
   The current adapter is `mugen/core/gateway/knowledge/chroma_http.py`.
3. Preserve tenant/database routing, authentication headers, configured timeouts,
   and metadata filters, including the `$and` conversion for multiple predicates
   currently implemented in the adapter. Keep local embeddings with
   `trust_remote_code=False`; server collection metadata must not choose or load
   an embedding function.
4. Verify collection lookup, query, upsert, deletion, and connection cleanup
   against the supported server API. Retain equivalent HTTP and gateway regression
   coverage, then run the complete test suite, 100% coverage gate, and full E2E
   validation. Confirm the resulting dependency graph does not reintroduce the
   alerts.

The return to an SDK depends on a verified upstream release; no release date is
assumed. Separately deployed Chroma servers still require their own remediation.

## Validation and GitHub closure

- Complete test suite: **3,744 passed; 957 subtests passed**.
- Complete E2E validation: **26 passed; zero failed or skipped**.
- Required 100% coverage check: **passed**, with zero missed statements or branches.
- HTTP adapter and gateway integration checks: **13 passed; 28 subtests passed**.
- Poetry lock validation, hashed dependency export, and `pip check`: **passed**.
  All 153 dependencies applicable to the validation platform match their locked
  versions; the ChromaDB distribution is absent.
- GitHub alerts #134–139: **open; pending default-branch merge and reanalysis**.

No alerts are dismissed or accepted as a workaround. After merge into `develop`,
confirm that GitHub's dependency graph has processed the updated files and that all
six alerts have closed. A local dependency change alone does not establish GitHub
closure.

The earlier [SEC-06 container scan](sec06-container-review.md) remains a record of
its specific image and scanner database. This source remediation is not a new
container scan and does not change the Debian or base-image findings in that
report.
