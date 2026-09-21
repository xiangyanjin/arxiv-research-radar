# Configuration

Run commands from the repository root. The application keeps its research profile separate from generated state.

## Profile selection

The profile is selected in this order:

1. The file set by `ARXIV_RADAR_PROFILE`.
2. `config/profile.local.json`, when present.
3. The bundled `config/profile.json`.

Start with a local copy:

```bash
cp config/profile.json config/profile.local.json
```

The local copy is Git-ignored. Use an absolute path when setting an environment variable for a scheduler:

```bash
export ARXIV_RADAR_PROFILE="/absolute/path/to/profile.json"
export ARXIV_RADAR_DATA_DIR="/absolute/path/to/radar-data"
python3 -m radar scan
```

Every invocation that should share the same collection must use the same profile and data directory, including the dashboard, scan, review import, and notification commands.

## Profile fields

| Field | Meaning |
| --- | --- |
| `name` | Display name of the research feed |
| `display.name` | Display name used by the dashboard; defaults to `name` |
| `display.timezone` | IANA display timezone, such as `UTC` or `Asia/Shanghai`; does not schedule scans |
| `categories` | arXiv categories to retrieve, such as `math.PR` or `stat.ML` |
| `topics` | Topic IDs, labels, descriptions, keywords, category hints, and weights |
| `minimum_score` | Minimum rule-based relevance score for recommendations |
| `own_arxiv_ids` | Optional paper IDs to retain in storage but exclude from recommendations |
| `self_author_names` | Optional full author names to exclude from recommendations |
| `digest_limit` | Maximum papers per digest and exported review queue |
| `scan.lookback_days` | Initial scan window; the bundled default is 14 days |
| `scan.overlap_days` | Overlap before the last complete scan watermark |
| `scan.page_size` | Records requested per API page, capped at 1,000 |
| `scan.max_pages` | Maximum API pages per run; reaching the cap can mean partial coverage |
| `scan.timeout_seconds` | Per-request timeout, capped at 20 seconds |
| `scan.retries` | Retry count, capped at one retry |

Increasing the category range or lookback can require more pages and more time. The scanner processes requests serially with a delay of at least three seconds. [arXiv API usage terms](https://info.arxiv.org/help/api/tou.html)

## Adapting ranking

Choose specific phrases rather than broad words such as `model`, `learning`, or `gap`. Categories provide context; a category alone does not earn a relevance score.

The bundled `matrix`, `tensor`, `markov`, and `concentration` topic IDs have additional domain checks in `radar/ranking.py` to reduce ambiguous matches. If you replace these topics with an unrelated field, give the new topic a new ID. New topic IDs use their configured keywords as anchors.

A topic can set an optional `anchors` array to require a more specific contextual phrase alongside keyword matches. Retrieval categories and topic categories serve different purposes: the top-level list controls which papers are fetched; each topic's categories provide a relevance hint.

Weights and thresholds are heuristic controls. They are not learned from feedback, and scores are not calibrated probabilities. Inspect both useful recommendations and missed or irrelevant results before treating a configuration as suitable for your field.

## Local state

The default data directory is `data/` at the repository root. It contains the SQLite database, archived source responses, run manifests, digests, and notification records. These are generated files and excluded from Git.

Changing a profile reranks papers already in storage. Changing retrieved categories does not erase the existing collection. To evaluate an independent profile with a clean collection, choose a separate `ARXIV_RADAR_DATA_DIR`.

Back up your data directory if your saved papers and reading feedback matter to you. A Git clone contains source code, not your personal collection.
