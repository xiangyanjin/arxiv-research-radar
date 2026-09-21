# Reading library

The library stores three independent states: **saved**, **read**, and **hidden**. Marking a saved paper as read keeps its bookmark. Hiding a paper retains its notes and other states; use the Hidden view to restore it.

## Notes

Each paper can store up to 5,000 characters of plain-text notes. Save explicitly to write them to the local SQLite database. Cancel discards the editor draft. Drafts remain in the current browser tab's session storage across filtering, view changes, language changes and reloads; they are not a database backup or cross-device sync. Saving failures retain the draft.

The database records when a note was saved and the paper version at that time. If the source has not supplied a version, the association is explicitly unknown, never a fictional v0. A newer arXiv version retains the note and its original version label so you can recheck whether it still applies. Clearing the note clears its version association. The reading list labels these as user notes rather than model analysis or claims in the source paper.

## Filters and exports

- All, New, Updates and Unread show papers that meet the active research profile and are not hidden.
- Saved, Read and With notes preserve access to those managed papers even if a profile change lowers their relevance score. They still respect topic and search filters and omit hidden papers.
- Hidden shows hidden records, including those below the current relevance threshold.
- Search matches titles, authors, abstracts and saved notes. Unsaved drafts are not part of server-side search or export.
- Sort by relevance, latest source update/announcement date, or title. An old paper's revision date is different from its first publication date.

The two dashboard exports contain **every result in the current filtered view**, in its current order, without a digest-size limit. The Markdown reading list includes metadata, source links, reading state, and saved notes. The BibTeX export contains citation metadata.

For integrations, pass the same `topic`, `filter`, `q` and `sort` values to:

```text
GET /api/papers
GET /api/exports/bib?scope=view
GET /api/exports/markdown?scope=view
```

The existing `/api/exports/bib` request without `scope=view` retains its earlier behavior: prefer saved papers, otherwise export the configured number of top recommendations. Exporting a filtered view does not change stored reading states.

Update only the fields you intend to change:

```json
{"id": "paper-id", "saved": true, "read": true, "notes": "Check the moment assumptions."}
```

Send this object to `POST /api/library` from the local dashboard origin. Missing fields stay unchanged. Unknown fields, non-boolean state values, invalid IDs and oversized notes are rejected. The older `/api/feedback` endpoint keeps its mutually exclusive behavior for compatibility; new integrations should use `/api/library`.

## Existing collections

Database upgrades preserve the old saved/read/irrelevant status in the corresponding new state and leave the paper metadata and reviews intact. An old mutually exclusive value cannot recover whether a paper used to be both saved and read before that information was overwritten. Subsequent state changes are independent.

The source repository excludes local databases and browser drafts. Back up your data directory before moving or replacing a research collection; Git tracks the application, not your reading history.
