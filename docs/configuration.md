# Configuration

The application keeps each research profile separate from generated state. A profile can describe any field represented on arXiv; the bundled mathematics configuration is a demo and compatibility default.

The commands below use `python3 -m radar` from the repository root. An installed skill can run from any working directory using `python3 /absolute/path/to/arxiv-research-radar/scripts/radar.py` instead. See [the skill guide](agent-skill.md) for an example with separate profile and data paths.

## Choose a starting point

```bash
python3 -m radar profiles
python3 -m radar init-profile --preset ai-agents --output config/profile.local.json --name "My agent research" --timezone UTC
python3 -m radar validate-profile config/profile.local.json
```

Available presets are `math-statistics`, `ai-agents`, `quant-finance`, and `astrophysics`. The `profiles` command lists them; `init-profile` writes a user-owned copy. An existing output file is rejected rather than overwritten. Reuse that file or choose a new output path.

The `math-statistics` preset retains the default profile's `matrix`, `tensor`, `markov`, and `concentration` IDs and their mathematics-specific context rules. The other presets use their own topic IDs. A new field should likewise use descriptive custom IDs rather than inheriting an unrelated mathematical rule.

Presets are editable examples, not the set of allowed research interests. Your host agent can turn a description such as “LLM agents with tool-use evaluation” or “exoplanet atmosphere retrieval” into categories, topic IDs, keywords, and optional anchors. Inspect those choices and validate the resulting file. The CLI validates the configuration's structure and supported values; it does not prove that the profile finds everything relevant to your field.

## Profile selection

The profile is selected in this order:

1. The explicit `--profile` command-line argument.
2. The file set by `ARXIV_RADAR_PROFILE`.
3. `config/profile.local.json`, when present.
4. The bundled `config/profile.json`.

Place profile and data flags **after the subcommand**:

```bash
python3 -m radar scan --profile /absolute/path/to/profile.json --data-dir /absolute/path/to/radar-data
python3 -m radar serve --profile /absolute/path/to/profile.json --data-dir /absolute/path/to/radar-data
```

The data directory similarly uses `--data-dir`, then `ARXIV_RADAR_DATA_DIR`, then the repository's `data/` directory. Use absolute paths when invoking the installed skill or configuring a scheduler. Environment variables remain available:

```bash
export ARXIV_RADAR_PROFILE="/absolute/path/to/profile.json"
export ARXIV_RADAR_DATA_DIR="/absolute/path/to/radar-data"
python3 -m radar scan
```

Every invocation that should share the same collection must use the same profile and data directory, including the dashboard, scan, review import, and notification commands.

Relative `--profile` and `--data-dir` values, and their environment-variable equivalents, resolve against the repository/installed skill root. In contrast, `--output` files and positional input files resolve against the caller's current directory. The skill therefore uses absolute paths for both inputs and outputs, keeping behavior consistent when the agent changes directories.

`config/profile.local.json` is Git-ignored. You can still create it by copying `config/profile.json` if you prefer manual setup; `init-profile` is a convenient way to choose another starting point. Keep profiles outside the installed skill folder when you want a project-owned workspace that is separate from the software checkout.

## A custom direction

This complete, minimal profile starts a collection for exoplanet atmospheres:

```json
{
  "name": "Exoplanet atmospheres",
  "display": {"name": "Exoplanet atmospheres", "timezone": "UTC"},
  "categories": ["astro-ph.EP"],
  "topics": [
    {
      "id": "exoplanet_atmospheres",
      "label": "Exoplanet atmospheres",
      "keywords": [
        "exoplanet atmosphere",
        "exoplanet atmospheres",
        "transmission spectroscopy",
        "atmospheric retrieval"
      ],
      "anchors": ["exoplanet", "exoplanets", "transmission spectroscopy", "atmospheric retrieval"],
      "categories": ["astro-ph.EP"],
      "weight": 1.0
    }
  ],
  "minimum_score": 20,
  "digest_limit": 8
}
```

Save it as your own JSON file, run `validate-profile FILE`, then pass its absolute path to `scan` and `serve`. Omitted scan settings receive the defaults described below. Create distinct profile and data paths for independent collections; choosing a new interest does not require editing the bundled presets.

## Profile fields

| Field | Meaning |
| --- | --- |
| `name` | Display name of the research feed |
| `display.name` | Display name used by the dashboard; defaults to `name` |
| `display.timezone` | IANA display timezone, such as `UTC` or `Asia/Shanghai`; does not schedule scans |
| `categories` | arXiv categories to retrieve, such as `math.PR` or `stat.ML` |
| `topics` | Topic IDs, labels, descriptions, keywords, category hints, and weights |
| `exclude_keywords` | Optional global phrase list; any match excludes the paper from recommendations |
| `topics[].anchors` | Optional required context phrases; at least one must match alongside a topic keyword |
| `topics[].exclude_keywords` | Optional phrase list that blocks only this otherwise-matching topic |
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

Labels and descriptions can use your preferred language. Choose keyword phrases and synonyms that occur in the source metadata; a Chinese research request will generally need corresponding English phrases for arXiv title and abstract matching. This is configuration by the host agent, not a built-in semantic search model.

The bundled `matrix`, `tensor`, `markov`, and `concentration` topic IDs have additional domain checks in `radar/ranking.py` to reduce ambiguous matches. If you replace these topics with an unrelated field, give the new topic a new ID. New topic IDs use their configured keywords as anchors unless you explicitly supply an `anchors` list.

An explicit `anchors` array is a real requirement: at least one anchor must occur in the title or abstract as well as a topic keyword. The legacy mathematical context shortcuts do not bypass an explicit anchor list. Retrieval categories and topic categories serve different purposes: the top-level list controls which papers are fetched; each topic's categories provide a relevance hint.

Phrase matching normalizes case, accents, punctuation, hyphens, underscores, and whitespace. Equivalent configured spellings count once; for example, repeating `tool-use`, `Tool use`, and `tool_use` does not earn extra keyword credit. The first spelling is retained for explanation. A phrase must occur within a title or within an abstract, never across their boundary.

## Excluding phrases

Add a top-level `exclude_keywords` list for a global exclusion, or put that field inside one topic for a local exclusion. This is a configuration fragment, not a complete profile:

```json
{
  "exclude_keywords": ["medical diagnosis"],
  "topics": [
    {
      "id": "web-agents",
      "label": "Web agents",
      "keywords": ["web agents", "agent benchmarks"],
      "anchors": ["agent", "agents"],
      "exclude_keywords": ["chemical"]
    }
  ]
}
```

A global match suppresses the paper's recommendation regardless of other positive topics. A topic-level match blocks that topic only: another valid, unblocked topic can still recommend the paper. If every otherwise-eligible topic is blocked, the paper is excluded. Exclusion does not delete stored metadata, reading states, or notes; managed papers remain accessible in their library views.

These are **literal normalized phrase rules, not semantic exclusions**. `medical diagnosis` also matches “we do not address medical diagnosis.” Such rules can remove useful papers. A topic exclusion also does not distinguish different meanings of the same word. The example exclusions above illustrate mechanics; they are not defaults for every researcher.

The dashboard's **Match details** separates title matches, abstract matches, anchors, and exclusions, with explanations for missing context or blocked topics. These configured phrases are not verbatim source quotations. Preview a proposed profile against stored candidates before adopting it: [offline tuning workflow](profile-tuning.md).

Weights and thresholds are heuristic controls. They are not learned from feedback, and scores are not calibrated probabilities. Inspect both useful recommendations and missed or irrelevant results before treating a configuration as suitable for your field.

## Local state

The default data directory is `data/` at the repository root. It contains the SQLite database, archived source responses, run manifests, digests, and notification records. These are generated files and excluded from Git.

Changing a profile reranks papers already in storage. Changing retrieved categories does not erase the existing collection. To evaluate an independent profile with a clean collection, choose a separate `ARXIV_RADAR_DATA_DIR`.

Back up your data directory if your saved papers and reading feedback matter to you. A Git clone contains source code, not your personal collection.

Creating a profile or changing `display.timezone` does not enable a scheduled scan. Recurring execution is a separate action handled by an authorized external scheduler. Reading feedback remains local state and does not automatically train a preference model.
