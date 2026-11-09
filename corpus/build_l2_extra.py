"""
build_l2_extra.py — Extra L2 training data: corpus/l2_extra.jsonl.

L2 was trained on only 21 benign examples, so it learned "anything that reads
like a tool response is an injection" (benign FPR 0.67 on the test split,
1.00 on benign HTML/JSON probes). This file adds benign text from real
sources plus format-matched examples so the model cannot use format as a
shortcut:

  wiki        benign Wikipedia passages (SQuAD validation contexts)
  news        benign news leads (CNN/DailyMail test articles)
  hard_neg    hand-written benign declarative statements that resemble
              implicit injections (approvals, certifications, deadlines,
              recommendations) but are ordinary, attributable content
  html_benign benign text inside HTML pages with legitimate hidden elements
  json_benign legitimate JSON API responses
  html_inject TRAINING-split injections inside HTML (visible or hidden), so
              HTML is not a benign-only signal

Nothing here is evaluated. Corpus test-split entries are never used, and the
page templates differ from corpus/build_probes.py so the probe sets stay unseen.
Each entry carries `extra_split` = train / val (85/15) for threshold calibration.

Both sources load from the local HuggingFace cache (no download).
Usage:  python -m corpus.build_l2_extra
"""

import json
import os
import random
import re

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from datasets import load_dataset

from settings import CORPUS_PATH, ROOT
from training.dataset import load_raw, split_corpus

OUT_PATH = ROOT / "corpus" / "l2_extra.jsonl"
SEED = 7
N_WIKI, N_NEWS, N_HTML_BENIGN, N_HTML_INJECT, N_JSON = 120, 80, 70, 50, 30
VAL_RATIO = 0.15

HARD_NEGATIVES = [
    "Purchase orders above 10,000 dollars require approval from the finance director before they are issued.",
    "The supplier's ISO 14001 certificate was renewed in March; a copy is available on request from the quality team.",
    "According to the company's annual report, revenue grew by 6 percent compared with the previous year.",
    "The vendor states that its products meet EU REACH requirements; we have not independently verified this claim.",
    "Applications submitted after the 15 June deadline will be considered in the next funding round.",
    "Our editors recommend comparing at least three quotes before choosing a moving company.",
    "The product received a four-star rating from 1,240 verified buyers, with most complaints about delivery times.",
    "This hospital is accredited by the Joint Commission, which surveys facilities every three years.",
    "Registration for the conference closes on Friday; late registrations are not accepted.",
    "The firm was founded in 1998 and employs around 300 people across four offices.",
    "All new vendors complete a security questionnaire and a reference check before onboarding.",
    "The bridge passed its most recent structural inspection, according to the state transport department.",
    "Customers on the premium plan receive priority support with a four-hour response target.",
    "The study, published in a peer-reviewed journal, found a modest effect that the authors say needs replication.",
    "Stock is limited for the holiday period, so orders placed after 18 December may arrive in January.",
    "The council approved the planning application subject to conditions on noise and opening hours.",
    "This course is offered in partnership with a local college and counts toward its diploma programme.",
    "Independent reviewers rated the laptop highly for battery life but criticised its keyboard.",
    "The contractor holds public liability insurance of up to five million pounds.",
    "The regulator lists this bank as authorised; you can confirm its registration number on the public register.",
    "Prices shown include VAT; shipping is calculated at checkout.",
    "The recall affects batches produced between May and July; affected customers should contact the retailer.",
    "Several analysts expect interest rates to stay unchanged at the next meeting.",
    "Our refund policy allows returns within 30 days with proof of purchase.",
    "The audit identified two minor findings, both of which have since been closed.",
    "This charity is registered with the national charities commission under number 1182345.",
    "Shortlisted candidates will be contacted within two weeks of the closing date.",
    "The manufacturer recommends servicing the boiler once a year.",
    "Supplies of the vaccine are expected to increase next month, the health ministry said.",
    "The software is certified for use with the latest version of the operating system.",
    "The airline has been rated four stars by an industry ranking that assesses service and safety.",
    "Membership gives access to the library, the gym and discounted parking.",
    "Food safety inspectors awarded the restaurant the highest hygiene rating last spring.",
    "The tender documents ask bidders to provide two references from comparable projects.",
    "Our team reviewed the proposal and recommends a second round of quotes before deciding.",
    "The data centre is certified to Tier III, which means planned maintenance does not require downtime.",
    "This listing has been verified by the platform, meaning the seller confirmed their identity.",
    "Early bird pricing ends at midnight on Sunday.",
    "The law firm advises clients on mergers, employment disputes and commercial property.",
    "Farmers in the region reported higher yields after an unusually wet summer.",
    "The university ranks in the top 200 worldwide in a widely cited league table.",
    "The device is approved by the national telecoms regulator for sale in the country.",
    "Most reviewers describe the hotel as clean and quiet, though some mention small rooms.",
    "The fund's past performance does not guarantee future results, according to its prospectus.",
    "Delivery is free on orders over 50 dollars within the mainland.",
    "The pilot programme will be evaluated in December before any wider rollout is approved.",
    "The museum's collection includes more than 20,000 objects from the region's history.",
    "Our procurement policy requires at least two quotes for any purchase above 5,000 euros.",
    "The certification body publishes a list of certified companies on its website.",
    "The project is on schedule, according to the latest status report from the site manager.",
    "The company is a certified B Corporation, a designation awarded after an assessment of its social impact.",
    "The safety data sheet lists the product as non-flammable under normal conditions.",
    "Analysts at the bank describe the outlook for the sector as stable.",
    "Invoices are processed in the weekly payment run every Thursday.",
    "The clinic accepts most major insurance plans; check with your insurer before booking.",
    "The product is the best-selling model in its category, according to the retailer's sales data.",
    "Volunteers are needed for the weekend event; no prior experience is required.",
    "The building has an energy performance rating of B.",
    "The grant covers up to 50 percent of eligible project costs.",
    "The operator holds an air operator certificate issued by the civil aviation authority.",
]

# Page shells and decorations are shared by BOTH classes, chosen at random,
# so HTML layout carries no label information (an earlier version used one
# bare template for injections and the model learned it as a shortcut).
SHELLS = [
    "<html><head><title>{title}</title>{style}</head><body><h1>{title}</h1><p>{body}</p>{deco}{extra}</body></html>",
    "<html><body>{style}<header><h2>{title}</h2></header><article><p>{body}</p></article>{extra}{deco}<footer>Terms · Privacy</footer></body></html>",
    "<html><head>{style}</head><body><main><h3>{title}</h3><p>{body}</p>{extra}</main>{deco}</body></html>",
    "<div class=\"content\">{style}<h2>{title}</h2><p>{body}</p>{deco}{extra}<p>Last updated in October.</p></div>",
    "<html><body>{style}<section><h1>{title}</h1>{deco}<p>{body}</p>{extra}</section><p>Contact us for more information.</p></body></html>",
    "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title>{style}</head><body><div id=\"main\"><h2>{title}</h2><p>{body}</p>{extra}</div>{deco}</body></html>",
]

# (style, element) pairs: legitimate hidden or decorative elements
DECORATIONS = [
    ("", ""),
    ("", ""),
    ("<style>.skip{position:absolute;left:-10000px}</style>", '<a class="skip" href="#main">Skip to main content</a>'),
    ("", '<ul style="display:none"><li>Home</li><li>Shop</li><li>Help</li></ul>'),
    ("", '<form><label style="display:none" for="q">Search</label><input id="q"></form>'),
    ("", '<div style="visibility:hidden">Your preferences have been saved.</div>'),
    ("", "<!-- analytics snippet -->"),
    ("", '<nav><a href="/">Home</a> | <a href="/about">About</a></nav>'),
]

TITLES = ["Overview", "About us", "Product details", "Company profile", "Supplier information",
          "Service description", "News", "Frequently asked questions", "Background", "Our history"]

INJECTION_WRAPS = [
    lambda t: f"<p>{t}</p>",
    lambda t: f'<div style="display:none">{t}</div>',
    lambda t: f'<span style="font-size:0">{t}</span>',
    lambda t: f"<!-- {t} -->",
    lambda t: f'<p style="color:#fff;background-color:#fff">{t}</p>',
]

# Benign extras placed where injections go, so "an extra paragraph" isn't a signal either
BENIGN_EXTRAS = [
    "",
    "<p>Opening hours are 9am to 5pm, Monday to Friday.</p>",
    "<p>Prices are subject to change without notice.</p>",
    '<div style="display:none">Thank you for your message. We will reply within two working days.</div>',
    "<!-- section maintained by the web team; review quarterly -->",
]


def html_page(rng, body: str, extra: str) -> str:
    style, deco = rng.choice(DECORATIONS)
    return rng.choice(SHELLS).format(title=rng.choice(TITLES), body=body,
                                     deco=deco, extra=extra, style=style)


JSON_TEMPLATES = [
    lambda r: {"status": "ok", "count": r.randint(1, 500), "next_page": None},
    lambda r: {"order_id": f"SO-{r.randint(1000, 9999)}", "items": r.randint(1, 9),
               "total": round(r.uniform(5, 900), 2), "currency": r.choice(["USD", "EUR", "GBP"])},
    lambda r: {"city": r.choice(["Lisbon", "Osaka", "Denver", "Nairobi"]),
               "forecast_c": [round(r.uniform(5, 30), 1) for _ in range(5)]},
    lambda r: {"user": {"id": r.randint(1, 99999), "name": r.choice(["Ana", "Ken", "Priya", "Omar"]),
                        "roles": r.sample(["viewer", "editor", "admin"], 2)}},
    lambda r: {"invoice": f"INV-{r.randint(10000, 99999)}", "paid": r.choice([True, False]),
               "due": f"2026-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}"},
    lambda r: {"monthly_sales": [r.randint(100, 5000) for _ in range(6)], "region": r.choice(["EMEA", "APAC"])},
    lambda r: {"sha256": "".join(r.choice("0123456789abcdef") for _ in range(64)), "size_bytes": r.randint(1000, 10**7)},
    lambda r: {"message": "Record saved.", "updated_at": f"2026-10-{r.randint(1, 28):02d}T10:00:00Z"},
]


def first_sentences(text: str, max_words: int = 60) -> str:
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    out = []
    for s in sents:
        if len(" ".join(out + [s]).split()) > max_words:
            break
        out.append(s)
    return " ".join(out) or " ".join(text.split()[:max_words])


def main():
    rng = random.Random(SEED)
    rows = []

    def add(content, label, kind, subset):
        rows.append({"id": f"x_{kind}_{len(rows) + 1:04d}", "content": content, "label": label,
                     "subset": subset, "kind": kind, "source": kind})

    squad = load_dataset("squad", split="validation")
    contexts = list(dict.fromkeys(squad["context"]))      # dedupe paragraphs
    rng.shuffle(contexts)
    wiki = [first_sentences(c) for c in contexts[:N_WIKI + 40]]
    for t in wiki[:N_WIKI]:
        add(t, 0, "wiki", "benign")

    cnn = load_dataset("cnn_dailymail", "3.0.0", split="test")
    idx = rng.sample(range(len(cnn)), N_NEWS)
    for i in idx:
        article = re.sub(r"^.*?\(CNN\)\s*--\s*", "", cnn[i]["article"])
        add(first_sentences(article, 50), 0, "news", "benign")

    for t in HARD_NEGATIVES:
        add(t, 0, "hard_neg", "benign")

    bodies = wiki + [r["content"] for r in rows if r["kind"] in ("news", "hard_neg")]
    for _ in range(N_HTML_BENIGN):
        add(html_page(rng, rng.choice(bodies), rng.choice(BENIGN_EXTRAS)), 0, "html_benign", "benign")

    for _ in range(N_JSON):
        add(json.dumps(rng.choice(JSON_TEMPLATES)(rng)), 0, "json_benign", "benign")

    # Training-split injections in HTML (never val/test entries of the corpus)
    train = [e for e in split_corpus(load_raw(CORPUS_PATH))["train"]
             if e["subset"] in ("explicit", "implicit")]
    for i, e in enumerate(rng.sample(train, N_HTML_INJECT)):
        wrap = INJECTION_WRAPS[i % len(INJECTION_WRAPS)]
        add(html_page(rng, rng.choice(bodies), wrap(e["content"])), 1, "html_inject", e["subset"])

    for r in rows:
        r["extra_split"] = "val" if rng.random() < VAL_RATIO else "train"

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    print(f"Wrote {len(rows)} entries to {OUT_PATH}")
    print(Counter((r["kind"], r["extra_split"]) for r in rows))


if __name__ == "__main__":
    main()
