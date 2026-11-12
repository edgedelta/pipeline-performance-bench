# Saved OTLP measurements

Only page datasets and their provenance are kept here. These are recorded benchmark results; rendering pages does not rerun benchmarks.

- [Metrics ladder](2026-10-17/metrics-ladder/README.md): current metrics page.
- [Traces ladder](2026-10-18/traces-low/README.md): current traces page.

The [downloadable evidence archive](https://github.com/edgedelta/pipeline-performance-bench/releases/tag/untagged-7559f9a28ba799f80881) preserves all 1,574 original files, including earlier unsuccessful runs, configs, fixtures, logs, profiles, generated charts and screenshots. This is a draft release accessible to repository collaborators; public Pages and daily releases are unchanged. The archive contains a per-file SHA-256 manifest. `archive.json` records its checksum and original source commit.

Download with `gh release download otlp-pr29-evidence-20261018 --repo edgedelta/pipeline-performance-bench`. Verify with the included `SHA256SUMS`, then extract the archive to restore the original `previews/otlp/` layout. Historical report links point to the immutable pre-cleanup commit.
