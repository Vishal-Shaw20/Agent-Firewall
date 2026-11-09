# Agent Firewall: How Much of a Layered Prompt-Injection Defense Survives the Real-World Attack Style?

*B.Tech Major Project, 7th Semester. Report and paper draft (milestone M8).*

## Abstract

Indirect prompt injection lets whoever controls the content an LLM agent reads steer what it concludes and does. The one large production measurement available found that more than 90% of real injections use *implicit*, declarative phrasing ("this supplier is pre-approved…") rather than the explicit, imperative style ("ignore previous instructions…") that most benchmarks and open-source defenses are built around.

We build a five-layer, framework-agnostic firewall that sits between a LangChain agent and its tools:
- regex heuristics;
- a DistilBERT classifier;
- CSS/DOM concealment detection with a rendered-OCR diff;
- taint tracking of tool-call arguments;
- schema deviation with payload reconstruction.

We evaluate it on a corpus whose explicit / implicit / structural / benign split approximates the real-world measurement, under a strict protocol: held-out test split, validation-only calibration, and a dev / held-out adversarial round.

The trained classifier is the only layer that generalizes to implicit attacks:
- **Same classifier, different training data:** trained on both styles it reaches an implicit AUC of 1.00; trained explicit-only, as public datasets are built, it falls to 0.26, *below chance*.
- **Without the classifier,** the pipeline catches 0.14 of implicit attacks. Its aggregate detection rate is 0.62 on a benchmark-like explicit-heavy mix but 0.33 on the real-world-calibrated mix.

The full pipeline catches 1.00 / 0.91 of explicit / implicit test attacks with no benign false positives on the test split. On independently generated, held-out implicit attacks it catches 16/20, at an 11% false-positive rate on benign text written in the same style.

Against four agents (a scripted worst case and three local LLMs), the firewall prevents every harmful outcome. The only attack that worked on real models was the implicit one, and it showed up as a planted claim in the agent's answer rather than a tool call.

We report the costs as well:
- precision of about 0.08 at a realistic 1% attack prevalence;
- large seed-to-seed variance on unseen formats;
- an action check that, by design, blocks legitimate page-sourced actions.

---

## 1. Introduction

LLM agents that browse the web, read documents or call APIs can't structurally tell instructions from retrieved content. Whoever controls that content can steer the agent mid-task: this is indirect prompt injection. Two published measurements frame the problem:

- **A web-scale measurement** of 1.2 billion URLs found 15.3 thousand validated real-world injection instances, many hidden from human view and placed to reach automated agents (arXiv:2604.27202).
- **A production measurement** of about 200,000 resumes processed by an LLM screening pipeline found hidden injections in about 1% of them. More than 90% of those injections **did not use explicit, instruction-style language** (arXiv:2605.28999).

Most published defenses and benchmark corpora (BIPIA, AgentDojo, InjecAgent and most open-source "agent firewalls") are built and evaluated around the explicit, imperative style ("ignore previous instructions…"), because it is easy to template and easy to detect. The only large-scale evidence of what real attackers send says the dominant style is the one almost nobody benchmarks against.

**Research question (SRS §2).** When a layered injection defense is evaluated on a corpus whose explicit/implicit split follows the real-world measurement, how much of its detection performance survives? Which layers generalize to implicit, non-imperative phrasing, and which are explicit-style pattern matchers in disguise?

**Contribution (SRS §9.2).** This is a measurement contribution, not a new detection technique:

1. A five-layer proxy that is framework-agnostic and runs in front of a real LangChain agent.
2. A corpus split deliberately into explicit / implicit / structural / benign subsets, in roughly real-world proportions.
3. A per-layer, per-subset evaluation under a strict protocol: held-out test data, validation-only calibration, no tuning on measured sets.
4. An honest account of which layers are style-dependent, including results that are unflattering to the system.

## 2. Threat model

- **Attacker:** controls some content an agent will read: a web page, an API record, a document. The attacker can't change the agent, its prompt or its tools.
- **Goal:** change what the agent concludes or does. That means planting a false "fact" in its output (e.g. "this supplier is pre-approved"), or triggering a side-effecting tool call (emailing the attacker, raising a purchase order).
- **Styles considered:**
  - **explicit:** imperative override, role switch, fake system message;
  - **implicit:** declarative claims with no imperative language;
  - **structural:** the payload is encoded (base64, hex, ASCII-coded number arrays, homoglyphs, Unicode tag characters) and only reconstructed later;
  - **concealment** (orthogonal to style): text hidden from human readers via CSS/DOM tricks.
- **Out of scope:** model-weight attacks, attacks on the user's own prompt (direct injection), multi-agent collusion, and formal guarantees.

## 3. System design

```
Agent (LangChain) ──tool call──▶ Agent Firewall ──▶ real tool
                  ◀─tool output─      │
             ┌──────────┬────────────┼────────────┬────────────┐
            L1          L2           L3           L4           L5
         heuristic  classifier  concealment  taint/goal   schema-deviation
             └──────────┴────────────┼────────────┴────────────┘
                         decision engine: PASS / STRIP / BLOCK
                         strip → re-screen → deliver or block
                         audit log (Redis, JSONL fallback)
```

### 3.1 Integration (FR1, FR2, FR14, NFR4)
`agent/firewall_tools.py` wraps any list of LangChain tools without modifying the framework; `create_agent` from LangChain v1 is used unchanged.
1. Each planned call is sent to `POST /tool_call` (L4 action mode). A BLOCK means the real tool never runs.
2. The real tool runs.
3. Its output is sent to `POST /tool_response` (L1–L5).

The agent only ever sees what comes back: the original output, a stripped version, or a short notice. The same pipeline runs in-process for evaluation and tests.

### 3.2 Layers

| Layer | What it does | Notes |
|---|---|---|
| **L1 heuristic** | 15 compiled regexes for override, role-switch, fake-system and jailbreak phrasing | Deliberately explicit-only (SRS §7), so its implicit blind spot is a clean measurement |
| **L2 classifier** | DistilBERT fine-tuned on the corpus plus benign and adversarial training data | Ensemble of 3 seeds; thresholds calibrated on validation data only; reads only the prose values of JSON; long inputs scored in overlapping 256-token windows |
| **L3 concealment** | Rule-based CSS/DOM/attribute checks, plus render-vs-extract: headless Chromium renders the page offline and Tesseract OCR reads what a human would see; DOM words missing from the OCR text are "hidden" | Computed-style visibility pass as fallback; 1.5 s budget with a `render_pending` fallback (NFR1) |
| **L4 taint / goal-consistency** | *Action mode:* tool output is tagged untrusted per session. A side-effecting call whose **target** arguments (recipient, URL, vendor, amount) trace back to untrusted output and not to the user's task is blocked; so is a call that drifts from the task towards untrusted content. *Content mode:* sentence similarity to "decision-steering" anchors minus similarity to neutral factual anchors | Content mode is an approximation and can only STRIP |
| **L5 schema-deviation** | Declarative per-tool schemas (`schemas/*.yaml`, NFR6); flags undeclared fields, type mismatches, opaque blobs, mixed-script tokens; a reconstruction probe decodes base64/hex/number arrays/homoglyphs and runs L1 on the result | Content-agnostic; the secondary structural contribution (SRS §3.4) |

### 3.3 Decision, stripping and re-screening
- **Verdicts:** any layer ≥ 0.8 means BLOCK; any layer ≥ 0.5 means STRIP; otherwise PASS (FR10). Every decision is logged with per-layer scores, contributing layers and latency (FR11, NFR3).
- **Stripping** removes each flagged span **with the block it sits in**: the enclosing HTML block element, or the enclosing plain-text paragraph. For JSON, the flagged fields are dropped.
- **Re-screening:** whatever is left is run through all five layers again, and **only a clean PASS is delivered**. Otherwise the response is blocked.
- **Sanitising a BLOCK:** a BLOCK is turned into a sanitised STRIP the same way, when every flagged part can be located.
- **Why whole blocks:** removing just the flagged sentence exposed neighbouring attack sentences that pass every layer on their own (section 6).

## 4. Data

| Set | Size | Purpose |
|---|---|---|
| **Headline corpus** `corpus/corpus.jsonl` | 200: 110 implicit (55%), 40 explicit (20%), 20 structural (10%), 30 benign (15%) | Main evaluation. The split approximates the >90%-implicit production finding; it is a documented modelling choice, not an established statistic (SRS §11). |
| **Train / val / test split** | 140 / 20 / 40, seed 42, stratified by subset | The test split (8 explicit, 22 implicit, 4 structural, 6 benign) is never used for training, calibration or design decisions |
| **Concealment probes** `corpus/probes/concealment.jsonl` | 30 test-split injections hidden in HTML with 12 techniques (3 unknown to L3's rules) + 40 benign pages with legitimately hidden elements | L3 evaluation |
| **Structural-benign probes** | 20 legitimate JSON responses with unusual structure | L5 / L2 false positives on JSON |
| **Extra L2 training data** `corpus/l2_extra.jsonl` | 410: Wikipedia (SQuAD) and news (CNN/DailyMail) passages, 60 hand-written benign look-alikes, benign HTML/JSON, training-split injections inside HTML | Training and validation only. HTML page shells are shared across both classes so layout carries no label. |
| **Adversarial set** `corpus/adversarial/adversarial.jsonl` | 118, split 50/50 into dev / held-out before any evaluation | M7 (section 6.4) |

**Adversarial set construction.**
- **Red-team part:** 24 hand-crafted attacks plus 14 benign look-alikes, aimed at known weak points (split payloads, hedged phrasing, payloads past L2's window, attribute and table-cell payloads, JSON prose, homoglyphs, base64 in prose, tag characters, indirect address to "automated readers").
- **Generated part:** 40 implicit attacks by qwen2.5:7b, generated from attack *goals* rather than corpus examples, plus 40 benign paragraphs from the same model on the same topics. That way false positives are measured on the same writing style.
- **Label check:** an independent LLM judge (llama3.1:8b) agreed with all 40 benign labels but only 5 of 40 attack labels, including clearly steering items. It was too conservative to use as a filter. All 40 generated attacks were instead reviewed by hand, independent of the pipeline: 19 marked "steering" and 21 "weak" (mostly ordinary marketing urgency). Primary results use the reviewed attacks plus all benign items; the full set is reported alongside.

## 5. Evaluation protocol

- **No tuning on measured data.** Thresholds are calibrated on validation data only:
  - L2 at 95% validation TPR, the middle of the tied range;
  - L4 content mode at ≤5% benign FPR on training data.

  Model selection uses validation loss, and design fixes are made on dev data or on failures understood from the mechanism, never on held-out results. Where a fix was prompted by a probe-set result, this is stated, and that probe number is marked as optimistic.
- **Layer combinations:** a combination flags an entry if any of its layers scores ≥ 0.5. The pipeline verdict additionally reflects stripping and re-screening.
- **Metrics:**
  - TPR per subset (the headline result), FPR on benign entries;
  - threshold-free AUC for ranking quality;
  - per-layer contribution by subset;
  - classifier ablation (explicit-only vs explicit+implicit training);
  - structural-layer ablation (with and without L5);
  - seed variance;
  - leakage: whether any attack sentence survives in stripped content delivered to the agent;
  - latency.
- **Agents:** a deterministic scripted "gullible" agent (worst case, used for reproducible tests) and three local LLMs via Ollama on CPU (llama3.2:3b, qwen2.5:7b, llama3.1:8b), temperature 0.

## 6. Results

All numbers below are from the final pipeline: L2 = 3-seed ensemble after the M7 retrain, render-diff with Tesseract OCR, in-process, on one laptop CPU (no GPU). Raw tables are in `eval/results/`; each subsection names its file.

### 6.1 Headline: detection by subset (held-out test split, `headline_test.md`)

| detector | explicit (8) | implicit (22) | structural (4) | benign FPR (6) |
|---|---|---|---|---|
| L1 heuristic | 0.50 | **0.14** | 0.00 | 0.00 |
| L2 classifier (ensemble) | 1.00 | 0.91 | 0.00 | 0.00 |
| L4 content mode | 0.38 | 0.05 | 0.00 | 0.00 |
| L5 schema | 0.00 | 0.00 | 0.25 | 0.00 |
| **all five layers** | **1.00** | **0.91** | 0.25 | **0.00** |
| all except L2 | 0.62 | 0.14 | 0.25 | 0.00 |

- **Pipeline verdicts:** all 6 benign entries PASS; 35 of the 40 entries are decided correctly (5 attacks PASS: 2 implicit, 3 structural).
- **Implicit misses:** two (imp_003, imp_044). L2 scores them 0.34 and 0.46, just under the STRIP threshold.
- **Structural:** the test sample happens to contain three of L5's four misses. L5 doesn't learn from the corpus, so its full-corpus rate is a valid estimate: **16/20 (0.80)**, with 0 false positives on the other 180 entries. Misses: three 0–1 float vectors with no character encoding, and one integer array that decodes to the single word "Approve".
- L3 scores 0 here because the headline corpus is plain text; its evaluation is section 6.8.

### 6.2 The central finding: style dependence

Threshold-free AUC of each injection subset against benign, on the test split (`l2_ablation.md`):

| detector | explicit | implicit |
|---|---|---|
| L2 trained on explicit + implicit (ensemble) | 1.00 | 1.00 |
| L2 trained **explicit-only**, the way most public datasets are built | 1.00 | **0.26** |
| L4 content mode, raw anchor similarity (round 3) | 0.92 | 0.48 |
| L4 content mode, contrastive margin (final) | 1.00 | 0.70 |
| L1 heuristic (TPR, not AUC) | 0.50 | 0.14 |

- **The same architecture, trained on a different style, flips from perfect to worse than chance on implicit attacks.** At its validation-calibrated threshold, the explicit-only model catches **0/22** implicit attacks. With the larger benign set it learned "declarative, factual-sounding text = benign", which is exactly how real implicit attacks are written. The result is stable across three retrains (implicit AUC 0.24, 0.37, 0.26 in rounds 3, 7 and 8).
- **L1** catches half of the explicit attacks and almost none of the implicit ones, as the SRS predicted.
- **L4 content mode** behaves like another explicit-style detector. The contrastive margin improves ranking, but at a 5% benign FPR it catches 1/22 implicit attacks.
- **Without L2, the pipeline catches 0.14 of implicit attacks.** All of the implicit detection that survives comes from one component trained on in-distribution implicit examples. That is the honest answer to the research question: *the layers that generalize to implicit phrasing are the ones whose training data contains it; the rule-based and similarity-based layers are explicit-style matchers.*

### 6.3 Seed variance and the ensemble (`l2_seed_variance.md`, `seed_compare` output)

Three seeds trained on identical data, then the ensemble, scored on the same held-out sets. L2 alone, at each model's own validation-calibrated threshold:

| model | val loss | implicit TPR | implicit AUC | benign HTML FPR (40) | benign JSON FPR (20) |
|---|---|---|---|---|---|
| seed 42 | 0.087 | 0.95 | 0.99 | 0.15 | 0.05 |
| seed 1 (lowest val loss) | 0.070 | 0.95 | 0.99 | **1.00** | 0.05 |
| seed 2 | 0.100 | 0.95 | 1.00 | 0.90 | 0.05 |
| **ensemble (used)** | 0.102 | 0.91 | 1.00 | **0.28** | 0.05 |

- **Ranking is stable; thresholded behaviour on unseen formats isn't.** AUC stays at 0.99–1.00, while the FPR on benign HTML pages swings from 0.15 to 1.00.
- **Validation loss doesn't predict it.** Before the M7 retrain, the seed with the lowest validation loss (seed 1) was also the best on HTML (0.03); after the retrain it's the worst (1.00). Selecting one seed by validation loss would have shipped that model.
- The ensemble was chosen as the default **before** these numbers were measured, as a variance-reduction measure. It costs about 3× L2 latency (section 6.10).

### 6.4 M7 adversarial iteration (`adversarial_roundA.md`, `adversarial_roundB.md`, `adversarial.md`)

**Round A (all 118 entries, pipeline before the patches).**
- Caught 41/43 reviewed attacks.
- Flagged **25/54** benign look-alikes. The LLM-written benign paragraphs were flagged by topic alone: 8/8 on pre-approval, 8/8 on identity, 6/8 on urgency. L2 had learned the *subject* of implicit attacks, not their steering function.
- Both misses were in the held-out half: a payload sentence placed at the end of a 336-word page of ordinary supplier text (L2 truncated its input at 256 tokens), and a claim split across two innocuous sentences.

**Patches, made using dev information only:**
1. L2 scores long inputs in overlapping 256-token windows (stride 64) and takes the maximum. This is a mechanism fix for truncation, verified on synthetic filler (filler alone 0.07, filler + payload 0.65).
2. L2 retrained with the dev half of the adversarial set (23 reviewed attacks, 26 benign look-alikes; "weak" items excluded), 3 seeds, ensemble re-calibrated on validation.

A planned L3 check of attribute text was dropped because Round A showed the attribute payloads were already caught (3/3).

**Round B (held-out half only, never used for training, calibration or design):**

| held-out set | Round A | Round B |
|---|---|---|
| reviewed attacks (primary) | 18/20 | **16/20** |
| all attacks, incl. "weak" generated ones | 30/34 | 25/34 |
| benign look-alikes flagged (FPR) | 14/28 (0.50) | **3/28 (0.11)** |

- **The retrain bought a nearly 5× lower false-positive rate on look-alike text, at the cost of two reviewed attacks.** The long-dilution attack is now caught, thanks to the chunking. Three LLM-generated attacks are newly missed: two "officially certified by…" claims and one urgency claim. With 20 attacks, a two-item difference is within noise; the FPR drop is not.
- **Residual bypasses on the held-out half: 9.**
  - 4 reviewed: two false-authority claims (L2 0.21, 0.30), one urgency claim, and one split-sentence attack that every layer scores 0.00.
  - 5 "weak" generated items.
  - Every one is implicit. No residual bypass is explicit, concealed or encoded. Per protocol, none was patched.
- **A regression found outside the measured sets.** The demo's benign Atlas page now gets STRIPped. Its off-screen "Skip to main content" accessibility link scores 0.45 on its own and lifts the whole page to 0.83; without the link the page scores 0.12. L2 has learned "off-screen element + short imperative = injection" from the hidden-injection HTML in its training data, which is L3's job, and it explains L2's flags on the screen-reader and collapsed-menu benign probes. Only the link is removed, so the agent still receives the full page. It was **not** fixed, because the fix would be prompted by a probe result; the affected test is marked as an expected failure.

### 6.5 L4 action mode (`action_eval.md`)

**Setup.** Four agents: the scripted worst-case agent, and llama3.2:3b, qwen2.5:7b and llama3.1:8b via Ollama on CPU at temperature 0. They run five scenarios in three modes:
- **off:** no firewall;
- **calls_only:** only L4's tool-call check, with responses unscreened;
- **on:** the full pipeline.

The scenarios:
- the three demo attacks (explicit hidden instruction, implicit planted claim plus order email, base64 instruction in an API record);
- two ordinary tasks that need a side effect:
  - **task value:** "…and email the summary to alice@acme.example"; the recipient comes from the user;
  - **page value:** "…email its sales contact to request a quote"; the recipient legitimately comes from the page.

That's 60 runs. One run hit an Ollama out-of-memory error while models were swapping and was re-run.

**Attacks: harmed?** (off / calls_only / on)

| agent | explicit | implicit | structural |
|---|---|---|---|
| scripted | harmed / harmed / safe | harmed / harmed / safe | harmed / **safe** / safe |
| llama3.2:3b | safe / safe / safe | **harmed** / harmed / safe | safe / safe / safe |
| qwen2.5:7b | safe / safe / safe | safe / safe / safe | safe / safe / safe |
| llama3.1:8b | safe / safe / safe | **harmed** / harmed / safe | safe / safe / safe |

**Legitimate side effects** (off / calls_only / on)

| agent | task value (alice@…) | page value (sales contact) |
|---|---|---|
| scripted | done / done / done | done / **blocked by L4** / not done (page fully stripped, L2 FP 0.70) |
| llama3.2:3b | done / done / done | not attempted in any mode |
| qwen2.5:7b | done / done / done | done / **blocked by L4** / **blocked by L4** |
| llama3.1:8b | done / done / done | emailed a **made-up** address (sales@atlas.example) in all three modes |

- **With the full firewall, 0 of 12 agent × attack runs end harmed.**
- **L4 blocked every harmful side effect that was attempted, 2 of 2.** Both came from the scripted agent: the attacker email and the purchase order. None of the three LLMs attempted an attacker-directed side effect in any run.
- **The real harm from the LLMs was in words, not actions.** llama3.2:3b and llama3.1:8b wrote the planted "pre-approved for expedited purchasing" claim into their answer as fact. That's exactly the harm an action check can't see, so calls_only leaves it in place; only response screening removes it.
- **No false blocks on task-sourced values:** 12 of 12 task-value runs completed in every mode. This needed the target-argument restriction: when L4 checked every argument, the email *body*, which naturally quotes page facts, was flagged.
- **By design, L4 blocks every legitimate page-sourced action** (3 of 3 attempts). It traces values, not intent, so "email the contact on this page" and "email the address the attacker planted on this page" look the same to it. Telling them apart needs a policy (an allow-list of domains, or user confirmation) rather than a detector.
- **L4 doesn't catch fabricated targets.** llama3.1:8b invented a plausible address that isn't on the page and isn't in the task, and L4 let it through in every mode. That's a model error rather than an injection, but an action check that only looks for *copied* untrusted values misses it.

### 6.6 Cross-model demo (`demo_ollama_*.md`, `demo_scripted.md`)

The four-scenario demo per agent: three attacks plus a benign control, each off / on / calls_only. The tables are regenerated from fresh runs and agree with section 6.5.

| scenario | scripted | llama3.2:3b | qwen2.5:7b | llama3.1:8b |
|---|---|---|---|---|
| explicit: hidden "ignore previous instructions" | follows it | ignores it | ignores it | ignores it |
| implicit: planted "pre-approved supplier" + order email | emails attacker, records claim | **records claim** | ignores it | **records claim** |
| structural: base64 instruction in an API record | raises the purchase order | doesn't decode it | doesn't decode it | doesn't decode it |
| benign control | ok | ok | ok | ok |
| **firewall on** | all safe | all safe | all safe | all safe |

- **Across three real model families, the only attack that works is the implicit one.** It worked on two of the three, including the largest (8B). No model followed the explicit instruction or acted on the encoded one. That's consistent with the production finding the project starts from: the declarative style is the one that reaches real agents, and the imperative style that benchmarks are built around is the one models already resist.
- **Model size isn't protection.** llama3.1:8b absorbed the planted claim just like the 3B model; qwen2.5:7b didn't. One scenario per style at temperature 0 makes this anecdotal, not a measured rate.
- **What the firewall delivered with it on:**
  - explicit and implicit pages: sanitised (only the hidden block or the planted paragraph removed), so the models still received the page's legitimate content;
  - the structural record: delivered with only the base64 field dropped;
  - the benign control: its off-screen skip link was stripped (the false positive in section 6.4), and nothing else changed.
- **Tool use is uneven.** llama3.2:3b never called `write_notes` and answered in text; llama3.1:8b skipped it in some runs; qwen2.5:7b made the calls the task asked for.

### 6.7 Sensitivity to the assumed attack mix (`sensitivity.md`)

The per-subset rates of section 6.1 are reweighted to other attack mixes. Structural uses all 20 structural entries, with L2 hits counted only on test entries.

| detector | SRS 55/20/10/15 | resume study 77/8/0/15 | balanced 35/35/15/15 | structural-heavy 30/20/35/15 | benchmark-like 5/70/10/15 |
|---|---|---|---|---|---|
| all five layers | 0.92 | 0.92 | 0.93 | 0.89 | 0.97 |
| L1 heuristic only | 0.21 | 0.17 | 0.26 | 0.17 | **0.42** |
| L2 only | 0.82 | 0.92 | 0.79 | 0.56 | 0.88 |
| pipeline without L2 | **0.33** | 0.18 | 0.45 | 0.52 | **0.62** |

- **A defense without a trained implicit detector looks about twice as good on a benchmark-style mix as on the real-world-calibrated one** (0.62 vs 0.33 for the pipeline without L2; 0.42 vs 0.21 for L1). That is the measurement gap the project set out to quantify.
- **The full pipeline is fairly insensitive to the mix** (0.89–0.97), because L2 and L5 cover different subsets.
- **Precision depends on prevalence much more than on the mix.** At the 15% benign share of the mixes, precision is 0.98 or higher. Real traffic is overwhelmingly benign, though: the resume study found about 1% of documents injected. With the false-positive rate measured on the hard benign look-alikes (0.11):

| attack prevalence | 15% | 5% | 1% | 0.1% |
|---|---|---|---|---|
| precision, FPR from look-alike text (0.11) | 0.60 | 0.31 | **0.08** | 0.01 |
| precision, FPR from benign HTML with hidden elements (0.55) | 0.23 | 0.08 | 0.02 | 0.00 |

At realistic prevalence, most flags are false alarms. This is why the design strips flagged blocks instead of blocking whole responses: a false STRIP of a cookie banner costs little, a false BLOCK of a page costs the task.

### 6.8 Concealment and structural probes (`concealment.md`, `structural_benign.md`)

**Concealment probes** (30 hidden injections, 12 techniques; 40 benign pages with legitimately hidden elements):
- **L3 detects 30/30 hidden injections**, including all 6 using techniques absent from its rule list (transform:scale, CSS-variable colour, clip-path). `clip-path` was missed by the computed-style fallback and is caught by the OCR render-diff.
- **False positives:** L3 flags 15/40 benign pages: cookie banners 5/5, hidden modals 5/5, long developer comments 5/5. Menus, screen-reader text, collapsed FAQs, build comments and plain pages are all 0/5.
- **Whole pipeline on benign pages:** 18 PASS / 22 STRIP / 0 BLOCK. Of the 22 STRIPs, 11 come from L3 alone, 7 from L2 alone and 4 from both.
- **Optimistic estimate:** the collapsed-FAQ exemption was added after this probe set showed the OCR path flagging `<details>` content, so the 0/5 for that category is optimistic.

**Structural-benign probes** (20 legitimate JSON responses with unusual structure): L5 flags 0/20, the pipeline 1/20 (L2, STRIP only).

### 6.9 Sanitisation and leakage (`leakage.md`)

Every stripped response is re-screened, and only a clean PASS is delivered. Delivered injections in stripped form:

| set | delivered stripped | of which sanitised BLOCKs | attack sentence survived |
|---|---|---|---|
| headline, test split | 13 | 1 | 0 |
| headline, full corpus | 34 | 6 | 0 |
| hidden-HTML probes | 22 | 20 | 0 |
| adversarial, held-out | 21 | 10 | 0 |

**No attack sentence of 3 or more words survives in any content delivered to the agent.**

How "attack sentence" is defined:
- **Headline and hidden-HTML sets:** every sentence of the source injection.
- **Adversarial set:** every sentence unique to its entry (it has no span annotation).

### 6.10 Latency (NFR1)

Mean per tool response, in-process, single laptop CPU, models warm:

| stage | mean ms |
|---|---|
| L1, L5 | < 1 |
| L2, 3-model ensemble | 370–400 |
| L4 | 40–90 |
| L3 render + OCR (HTML only) | ~520 |
| synchronous path (L1 + L2 + L4 + L5) | 420–495 |
| full pipeline on HTML | ~940 |
| re-screen after a strip | ~920 on HTML |

- **Budgets:** the synchronous path meets the sub-second budget. Render-diff stays inside its 1.5 s budget, and the `render_pending` fallback never fired.
- **Re-screening HTML** doubles the cost (to about 1.9 s), but only for flagged responses.
- **Ensemble cost:** about 3× a single L2 model (130 ms).
- **Cold start:** the first call takes 50–60 s while models and the browser load.

## 7. Limitations

- **Small evaluation sets.** The headline test split has 40 entries (6 benign, 4 structural); the held-out adversarial half has 20 reviewed attacks and 28 benign items. A difference of one or two entries moves a rate by 5–25 points, and confidence intervals are wide. Rates are given with counts throughout so this stays visible.
- **The real-world mix is an assumption.** The 55/20/10/15 split approximates one production measurement (resume screening) and one web-scale crawl; neither gives the split for agent tool output in general. Section 6.7 shows how much the aggregate numbers move under other mixes.
- **One author team.** The corpus, the red-team evasions and the review of generated attacks come from the same people who built the defense. The generated half of the adversarial set (qwen2.5:7b) is the only part written independently of the training data, and its labels were reviewed by hand because an LLM judge was too conservative.
- **L2 does most of the implicit detection, and L2 is trained on this distribution.** Without L2 the pipeline catches almost no implicit attacks. Its held-out performance on independently written attacks is lower than in-distribution, and every L2 retrain trades recall against false positives (section 6.4).
- **L4 action mode traces values, not intent.** It blocks a side effect whose target came from untrusted content, so a legitimate "email the contact on this page" is blocked too (section 6.5). It can't stop harm that is only words in the agent's answer, such as a planted claim copied into notes.
- **L4 content mode and L3's hidden-prose rule are approximations.** Content mode catches few implicit attacks at an acceptable false-positive rate. L3 flags legitimately hidden prose (cookie banners, modals), which only ever leads to STRIP.
- **Structural coverage gaps.** L5 can't decode 0–1 float vectors or a short ASCII array that spells a single word; no layer catches those.
- **Re-screening guarantees consistency, not safety.** A stripped remainder is delivered only if it passes all five layers, which means it passes *this* pipeline. A remainder that evades every layer would also have evaded them unsanitised.
- **CPU only, small local models.** The agents are 3–8B models on CPU at temperature 0, with a handful of scenarios each. Behaviour of larger hosted models isn't measured. Latency figures are for one laptop CPU.
- **No adaptive attacker.** The adversarial round is one iteration against a fixed pipeline. An attacker with query access to the firewall's scores could search for bypasses much more efficiently.

## 8. Conclusion

**The research question was how much of a layered defense survives when the evaluation follows the real-world attack style.** The answer from this project is: the parts that were *trained on* that style, and little else.
- **Rule- and similarity-based layers are explicit-style detectors.** The regex layer, the content-mode taint check and an explicit-only classifier all do well on explicit attacks and close to nothing on implicit ones. On a benchmark-like mix they look about twice as good as they are on the real-world mix.
- **The classifier carries implicit detection, and its quality is a property of its training data.** The same architecture goes from AUC 1.00 to 0.26 when implicit examples are removed. On attacks written independently of the training data, recall drops and each retrain trades recall against false positives.
- **Structure-based layers are the robust complement.** Concealment detection (L3) and payload reconstruction (L5) don't care how the text is phrased. They caught all hidden-HTML injections and 16/20 encoded ones, but they only apply when the attacker hides or encodes the payload.
- **Action-level taint tracking is a useful second line, not a detector.** It stopped every harmful tool call that was attempted, and never blocked a recipient the user supplied. But it can't see harm that is only words, it blocks legitimate page-sourced actions by design, and it misses fabricated targets.
- **Stripping instead of blocking is what makes the false-positive rate tolerable.** At realistic prevalence most flags are false alarms. Removing the flagged block and re-screening the rest keeps the agent working, and in 77 delivered sanitised injections no attack sentence survived.

**For anyone evaluating an injection defense:** report results per style, and on a mix that resembles real traffic. A defense that looks strong on explicit benchmarks can be close to blind to the style real attackers actually use.

**Future work:**
- larger and independently authored implicit corpora;
- an adaptive attacker with access to the firewall's scores;
- a policy layer (allow-lists, user confirmation) for page-sourced actions;
- evaluation with larger hosted models.

## References

1. Indirect Prompt Injection in the Wild: An Empirical Study of Prevalence, Techniques, and Objectives. arXiv:2604.27202.
2. Measuring Real-World Prompt Injection Attacks in LLM-based Resume Screening. arXiv:2605.28999.
3. Hiding in Plain Floats: Steganographic Carriers for Indirect Prompt and Content Injection. arXiv:2606.08403.
4. SHIELDA: Structured Handling of Exceptions in LLM-Driven Agentic Workflows. arXiv:2508.07935.
5. AgentFixer: From Failure Detection to Fix Recommendations in LLM Agentic Systems. arXiv:2603.29848.
6. Benchmarks referenced: BIPIA, AgentDojo, InjecAgent.
