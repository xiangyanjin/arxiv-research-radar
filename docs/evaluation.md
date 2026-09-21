# Relevance evaluation

Evaluation is offline and uses only Python's standard library. It reads metadata and explicit boolean relevance labels, runs the configured ranking rules, and returns a reproducible JSON report. It does not access arXiv, initialize the research database, or generate its own labels.

```bash
python3 -m radar evaluate examples/ranking-eval.json --profile config/profile.json --k 5 --output output/evaluation.json
```

Omit `--output` to print JSON. Omit `--profile` to use the usual environment/local/default profile selection. Supplying the bundled profile explicitly makes the bundled example reproducible even if you have a private profile override.

## Dataset format

```json
{
  "name": "My independently labeled collection",
  "kind": "human-labeled",
  "description": "Describe the field, dates, sampling procedure, annotators and relevance definition.",
  "cases": [
    {
      "relevant": true,
      "paper": {
        "id": "unique-record-id",
        "title": "Paper title",
        "abstract": "The actual source abstract.",
        "authors": ["Author name"],
        "categories": ["math.PR"]
      }
    }
  ]
}
```

`kind` must be `synthetic` or `human-labeled`; it records the provider's provenance claim, not independent verification. IDs must be unique. Labels must be JSON `true`/`false`, never strings or model-generated relevance scores. The report includes SHA-256 fingerprints of the canonical dataset and validated profile, the threshold, per-case scores, matching terms, and mismatches.

## Metric definitions

A case is recommended when its score reaches `minimum_score` and it is not excluded as the configured user's own paper. Ground truth comes only from `relevant`.

| Metric | Definition |
| --- | --- |
| Precision | True positives / all recommended cases |
| Recall | True positives / all relevant cases |
| F1 | 2 × TP / (2 × TP + FP + FN) |
| Precision@k | Relevant cases among the first **up to k recommended** cases / number actually returned |
| Recall@k | Relevant cases in that returned list / all relevant cases |
| `returned_at_k` | Actual size of the top-k list; always inspect this beside Precision@k |

An empty denominator produces JSON `null`, not a perfect score. No recommendations with some relevant cases gives recall zero. Ranking ties use ascending ID. The optional `k` must be between 1 and 1,000.

These measures describe **relevance decisions on the supplied candidate pool**. They do not measure whether arXiv retrieval found all relevant papers, correctness of generated reviews, or mathematical quality. Precision@k can look high on a very short list, so inspect list length and recall together. Do not compare results from different datasets or profiles without stating the changes.

## Bundled fixtures and next evaluation step

`examples/ranking-eval.json` contains 20 fictional cases written for the starter mathematics profile. They are a small regression suite, not held-out research data. Two deliberate challenges expose current limitations: a negated mention of random matrices can still match, and an eigenvalue paraphrase without configured keywords can be missed. The evaluator reports such failures; it does not change the ranking rules to hide them.

For a useful field evaluation, collect a dated sample of actual candidates including unrecommended ones, independently label relevance before reviewing model scores, document disagreements, and keep a held-out set separate from keyword tuning. Keep private annotations outside Git (for example in `data/`), and only publish metadata/labels you are authorized to share. No real-world accuracy claim is supplied by this project.
