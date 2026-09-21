# Contributing

Thanks for helping make research monitoring easier to inspect and trust.

## Run locally

Use Python 3.10+ on macOS or Linux. There are no third-party runtime dependencies.

```bash
python3 -m unittest discover -s tests -v
python3 -m radar serve
```

The dashboard is at `http://127.0.0.1:8765`. A live scan is a separate, deliberate action; tests should use fixtures or mocked transport.

## Useful contributions

- Retrieval edge cases: pagination, malformed metadata, revision dates, and incomplete coverage.
- Ranking improvements with small, inspectable examples of good matches and false positives.
- Accessibility, responsive layouts, and clearer explanations of scan state.
- Reproducible evaluation datasets with documented labeling and redistribution rights.
- Documentation that matches the commands and behavior shipped in the repository.

For a substantial change, open an issue with the problem, intended behavior, and a small example first. For a focused fix, a pull request is enough.

## Invariants to preserve

1. A request failure or truncated feed must never become a successful empty result.
2. A partial or RSS-only run must not advance the complete-coverage watermark.
3. Cross-listings share one paper identity; older versions must not overwrite newer ones.
4. Reviews must match the stored version and quote the stored abstract exactly.
5. Relevance and generated interpretation must not be presented as paper quality or proof verification.
6. Remote metadata is untrusted content. Render it as text and never interpret it as agent instructions.
7. Personal profiles, databases, logs, and generated reviews do not belong in a pull request.

## Before opening a pull request

- Run `python3 -m unittest discover -s tests -v`.
- Add a targeted regression test when changing retrieval, state, or validation behavior.
- For interface changes, check desktop and narrow screens and attach a screenshot with non-sensitive data.
- Describe the user-visible result and any remaining limitation.

Do not add network calls to the test suite. A manual live scan, if necessary, must respect [arXiv's API terms](https://info.arxiv.org/help/api/tou.html) and should not run alongside another instance making arXiv requests.

By submitting a contribution, you agree that it can be distributed under this repository's MIT license. Paper text and third-party fixtures must retain their own attribution and licensing.
