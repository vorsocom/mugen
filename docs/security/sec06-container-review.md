# SEC-06 container verification

Verified on 2026-09-05. **The image scan is not clean.** The Torch downgrade is
removed; existing ChromaDB and Debian vulnerabilities remain as listed below.
This report records a scan, not a claim that all container vulnerabilities are fixed.

## Build and inventory

- Final image: `mugen-sec06:review`
- Image ID: `sha256:0f683e7b037d2bfb9b7de1e20932b62342824e0ba670225b257ea93add7a2253`
- Official `python:3.12-slim` base, refreshed with `--pull`:
  `sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`
- Integrated develop revision: `ce992892986d35f572cc66e8f5e94f5372f6158b`,
  including SEC-03 and SEC-04, plus the SEC-06 source changes.
- Platform: Linux amd64; Debian 13.6; CPython 3.12.
- All **173 application packages** match the hashed Poetry export and lock.
  The base-image pip installer is separately visible in the inventory.
- `pip check` passes; imported Torch is **2.13.0+cpu**, CUDA runtime is absent,
  and the CPU tensor smoke check passes. No GPU distributions are installed.
- The actual pinned default model loads with safetensors and remote code disabled,
  producing a finite 768-dimensional embedding on CPU.
- Gateway and inventory regression checks: **104 passed, 17 subtests passed**.
- Trivy **0.74.0**, vulnerability database updated **2026-09-05 13:02:41 UTC**.
  The final scan completed at **2026-09-05 17:58:41 UTC**.

## Scan findings

Counts are package/advisory findings; one advisory can affect several OS packages.

| Inventory | Critical | High | Medium | Low | Unknown | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Debian packages | 3 | 51 | 56 | 57 | 6 | 173 |
| Installed Python packages | 1 | 2 | 5 | 1 | 0 | 9 |

Torch has **zero reported vulnerabilities** in this scan. This is a result for
the recorded scanner database and image, not a guarantee about future advisories.

Residual critical/high findings:

- `chromadb==0.6.3`: **CVE-2026-45833** (critical), **CVE-2026-45830** and
  **CVE-2026-45831** (high).
- Debian `perl-base`: **CVE-2026-13221**, **CVE-2026-42496**, and
  **CVE-2026-8376** (critical).
- Debian high advisory IDs (deduplicated): CVE-2025-69720, CVE-2026-11822,
  CVE-2026-11824, CVE-2026-16742, CVE-2026-41992, CVE-2026-42497,
  CVE-2026-48962, CVE-2026-54369, CVE-2026-57432, CVE-2026-57433,
  CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410,
  CVE-2026-9538.

The scanner reports no fixed version for these critical/high findings.
Six additional Python findings affect the base-image `pip==25.0.1`: five medium
and one low. The complete JSON report preserves package versions, advisory
references, severity sources, and any available fixed versions. These residual
findings require separate dependency/base-image review before claiming a clean scan.

## Reproduction and evidence

```bash
docker build --pull -t mugen-sec06:review .
docker run --rm --entrypoint python mugen-sec06:review scripts/verify_container_inventory.py
docker run --rm --entrypoint python mugen-sec06:review -m pip inspect
trivy image --image-src docker --scanners vuln --format json \
  --output trivy.json mugen-sec06:review
```

The recorded build used host networking because the validation host's Docker
bridge could not resolve package hosts. The normal Docker context was
copied to a Snap-accessible directory. The image was checked to exclude runtime
configs, pytest cache, and this report, and to include the integrated SEC-03 code.
The 22 SEC-06 source files were also checked against the main worktree.
These are validation-host workarounds and verification steps, not image requirements.

Local evidence is retained in `_dev/security/sec06/`: `image.json`,
`inventory-verification.json`, `python-inventory.json`, `trivy.json`, `trivy.log`,
`trivy-db-metadata.json`, `model-smoke.log`, `context-verification.txt`,
`source-verification.json`, build/test logs, and `sha256sums.txt`.
This report is excluded from the runtime image so recording its digest does not
change the image being reported.
