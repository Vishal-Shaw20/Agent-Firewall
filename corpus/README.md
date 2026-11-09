# Corpus

## corpus.jsonl — headline corpus (200 entries)

One JSON object per line:

| field | meaning |
|---|---|
| `id` | `imp_*`, `exp_*`, `str_*`, `ben_*` |
| `content` | the tool response text |
| `label` | 1 = injection, 0 = benign |
| `subset` | `implicit` / `explicit` / `structural` / `benign` (SRS 8.1) |
| `attack_type` | finer category, e.g. `false_preapproval`, `override`, `float_array` (null for benign) |
| `tool_name` | `web_fetch` (text) or `json_api` (JSON) — selects the L5 schema |
| `task` | the user task the agent was doing when it fetched this content (used by L4) |
| `source` | `handcrafted` |

Split: 110 implicit (55%), 40 explicit (20%), 20 structural (10%), 30 benign (15%).
That approximates the resume-screening finding that >90% of real injections are
non-explicit (SRS 8.1). It is a modelling choice, not an established statistic
(SRS Section 11).

Train / val / test split: `training/dataset.py::split_corpus`, seed 42, 70/10/20,
stratified by subset. Written to `models/l2_distilbert/split.json`.
Evaluation uses the test split only.

New subsets or attack types need no code changes. Add lines with a new
`subset` / `attack_type` value and the eval runner reports them.

## probes/ — layer probe sets (generated: `python -m corpus.build_probes`)

- `concealment.jsonl`: the 30 test-split injections hidden in HTML pages, one
  technique each (9 the L3 rules know, 3 they don't), plus 40 benign pages with
  legitimately hidden elements. Extra fields: `technique`, `technique_in_rules`, `source_id`.
- `structural_benign.jsonl`: 20 legitimate JSON responses with unusual
  structure, for measuring L5's false-positive rate.

## l2_extra.jsonl — extra L2 training data (generated: `python -m corpus.build_l2_extra`)

Training/validation only, never evaluated: benign Wikipedia and news text (local
HF cache), hand-written benign hard negatives, benign HTML/JSON, and
training-split injections inside HTML. HTML shells are shared across both
classes so layout carries no label information. `extra_split` = train / val.
