# Preview a research profile before applying it

`preview-profile` compares ranking decisions on a fixed metadata pool. It is entirely offline: it does not open the research database, contact arXiv or a model, or change the active profile or library. It can write a JSON or Markdown report when you specify a separate output file.

Use it to answer “which of these candidates would my new rules add or remove?” It cannot answer “did retrieval find all relevant papers?” or “is recommendation accuracy better?” Those are different questions.

## Try the six-record demonstration

Run from a repository checkout:

```bash
python3 -m radar preview-profile examples/profile-tuning-papers.json --profile examples/profile-tuning.json --baseline config/presets/ai-agents.json --format markdown
```

The input contains **six fictional metadata records**, with no real paper identifiers or relevance labels. Against the bundled AI-agent preset, the proposed profile produces:

| Change | Example | Rule effect |
| --- | --- | --- |
| Added | `synthetic-desktop` | Adds `desktop automation`, with `agent` as context |
| Removed | `synthetic-chemical` | Its otherwise-matching topic is blocked by `chemical` |
| Removed | `synthetic-medical` | The global phrase `medical diagnosis` excludes the paper |

The recommendation count changes from four to three. The remaining recommended examples are desktop automation, tool calling, and web agents. This demonstrates configuration mechanics, not an improvement in recommendation accuracy or a recommendation that all users exclude chemistry or medicine.

Get the complete machine-readable comparison with:

```bash
python3 -m radar preview-profile examples/profile-tuning-papers.json --profile examples/profile-tuning.json --baseline config/presets/ai-agents.json --format json --output output/profile-preview.json
```

An installed skill can use `python3 /absolute/skill/path/scripts/radar.py preview-profile ...` from any directory. Use absolute candidate, profile, baseline, and output paths to avoid mixing the skill root with the caller's working directory.

## Use your stored collection

Start with the profile and data directory that already belong to your collection:

```bash
radar_workspace="/absolute/path/to/radar-workspace"
python3 -m radar export-candidates --profile "$radar_workspace/profile.json" --data-dir "$radar_workspace/data" --output "$radar_workspace/candidates.json"
```

`export-candidates` includes **every stored paper**, including unrecommended, excluded, and hidden records. It exports only `id`, `title`, `abstract`, `authors`, and `categories`. It does not export notes, saved/read/hidden flags, assessments, or past scores. This is a snapshot of what the collection has already retrieved, not a complete arXiv dataset.

Create a proposal at a fresh filename, leaving the active profile in place:

```bash
cp "$radar_workspace/profile.json" "$radar_workspace/profile.proposed.json"
```

If that proposed filename already exists, reuse it or choose another name rather than overwriting earlier tuning work. Edit the copy's keywords, context anchors, exclusions, or threshold, then validate and compare:

```bash
python3 -m radar validate-profile "$radar_workspace/profile.proposed.json"
python3 -m radar preview-profile "$radar_workspace/candidates.json" --profile "$radar_workspace/profile.proposed.json" --baseline "$radar_workspace/profile.json" --format markdown --output "$radar_workspace/profile-preview.md"
```

Inspect added and removed papers, including useful candidates a new exclusion may suppress. The report does not apply the proposal. If you decide to adopt it, explicitly use the proposed profile for later commands or intentionally update your active profile. Keep the same data directory if you want to retain your reading library.

Changing retrieval categories in a proposed profile does not fetch new papers during preview. Their effect on future retrieval requires a later scan; the preview still sees only the supplied pool.

## Command and input contract

```text
preview-profile INPUT --profile PROPOSED.json
    [--baseline BASELINE.json] [--limit 10]
    [--format json|markdown] [--output REPORT]
```

`INPUT` is either an array of paper objects or an object containing a `papers` array. Each paper needs a unique nonempty `id`, a nonempty `title`, an `abstract` string, and string arrays for `authors` and `categories`. Use an empty abstract string when the source has none. Other fields are ignored; notes, prior scores, and generated reviews do not influence ranking.

A review queue is accepted, but it is already filtered and usually too narrow to expose false negatives. Prefer `export-candidates` when inspecting your local collection. Even that export cannot recover papers that were never retrieved.

`--profile` and `--baseline` follow the usual profile-path rules: relative paths resolve against the repository or installed skill root. The input and `--output` resolve against the current working directory. The CLI rejects an output path that would overwrite the candidate file, proposed profile, or baseline profile. Choose a distinct report filename; this protection is not a general versioning system for earlier reports.

## Reading the result

| Field | Meaning |
| --- | --- |
| `summary` | Candidate, recommendation, exclusion, and own-paper counts for the proposed profile |
| `ranked` | **All** candidate decisions, ordered by descending score and then ascending ID |
| `top_ids` | First up to `limit` recommended IDs |
| `comparison.added_ids` / `removed_ids` | Recommendation membership changes relative to the baseline |
| `comparison.changes` | Records whose score or recommendation status changed |
| `topic_decisions` within a ranked record | Title, abstract, anchor, and exclusion matches for each topic |
| SHA-256 fields | Fingerprints of the normalized input metadata and validated profiles |

`--limit` accepts 1–100. It limits `top_ids` and the recommended/excluded paper lists displayed in Markdown. It does **not** truncate JSON `ranked`, summary counts, or comparison membership changes. The default six-record example therefore still has six `ranked` records when run with `--limit 1`.

Phrase rules normalize case, accents, punctuation, and whitespace and count equivalent configured spellings once. They do not understand negation, word meaning, or uncatalogued synonyms. A global exclusion blocks the paper; a topic-local exclusion blocks only that otherwise-eligible topic, allowing a different unblocked topic to match. Explicit anchors must actually be present. See [configuration details](configuration.md#adapting-ranking).

For precision, recall, and other measured relevance metrics, use independently labeled data with [`evaluate`](evaluation.md). Keep evaluation data separate from the examples used to tune keywords. Neither preview nor candidate-pool evaluation measures full retrieval coverage.
