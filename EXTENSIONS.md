# Extensions

Every key under `extensions` in this repo's records, with a reason (STANDARD.md §4.4). `pdt check` fails a key that isn't listed here (C10).

| Key | What it holds | Source | Why it's an extension |
|---|---|---|---|
| `atus.activity_code` | The 6-digit lexicon code whose minutes the summary column holds: t010101 → `"010101"` | the 2003-25 coding lexicon and Sum0325_info.txt (rule atus_summary_from_lexicon) | STANDARD.md §4.5 lets a record name a code list for its values, but not a code that the variable itself stands for. Proposed for §4.5 in PublicDataToolkit Task 56. |
| `atus.activity_code_list` | The code list that code is in: `atus-lexicon-0325` | as above | as above |

An extension that a second dataset also needs is a proposal for the standard.
