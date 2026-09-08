# Roadmap

Ordered by what the measurements say, not by what sounds interesting.

## Done

- Perception: one JS pass over the DOM to a compact element list, per-snapshot
  ids, a CSS selector resolved at snapshot time for each element.
- Action space: `click`, `type`, `select`, `scroll`, `navigate`, `wait_for`,
  `extract`, `finish`, shared by every source plan. Failures come back as text
  rather than exceptions, so a plan can report why it stopped.
- One backend, local. `llm/discover.py` asks Ollama what is installed, keeps
  the models reporting tool support and takes the smallest. Measured per run
  on this CPU: `qwen2.5-coder:3b` ~122 s, `llama3.2` ~119 s, `qwen2.5:7b`
  ~203 s.
- **The savings-rate dashboard**, which is the product. Seven Vietnamese banks
  across seven tenors, captured into dated snapshots, compared, and shown as
  three KPI cards, a trend chart of up to three banks, and a sortable table
  with the best and worst rate per tenor coloured.
- Nine of the ten requested banks were proven unscrapeable — four approaches
  each — so the board comes from an aggregator with BIDV's own endpoint
  fetched every run as a cross-check. Every capture so far has matched BIDV
  exactly across all seven tenors.
- Rate credibility is per source and deliberately not the consensus model:
  two banks quoting different rates is the comparison, not a disagreement.
- `snapshots.py`: the history no source publishes. Same-day captures replace
  rather than accumulate, and one capture draws no trend line rather than a
  flat line through a single point.
- `capture_rates.py` for cron or Task Scheduler, with exit codes a scheduler
  can act on (0 captured, 1 nothing usable, 2 the cross-check disagreed).
- The sentence under the rate chart is a template filled from computed
  figures. One fact, stated exactly, with no model and therefore no guards.
- Macro and market series kept as a secondary tab: USD/VND, inflation, GDP per
  capita, through the full pipeline with credibility scoring, the timeseries
  module and a model-written paragraph behind both guards. `TopicEntry.category`
  records which kind a topic is.
- `src/scoring/`: provenance by lookup and conditional on verification,
  corroboration by arithmetic, one threshold that suspends itself until an
  authoritative publisher has actually been scraped.
- `src/timeseries/`: trend, period comparison at a caller-named scale,
  anomalies by z-score and Tukey IQR, movement expressed in percentage points
  for series that are already percentages.
- Chart engine: type chosen by a rule, including bars for sparse observations
  where a line would invent a reading between two years. Axis precision is
  chosen from the data's spread -- a rate chart spanning 5.70 to 6.20 printed
  "6" at every tick before that.
- 160 tests, none of which need a browser or a model.
- Removed: the gold and Bitcoin topics and their adapters, which always
  refused and demonstrated a path the remaining topics already demonstrate.
- Removed: the general browser agent and its saucedemo evaluation suite, plus
  the testing and RPA mode sketches built on it. The product is the research
  pipeline, whose steps are written down rather than chosen by a model, so the
  agent loop had no caller left. `src/actions/` and `src/perception/` stay --
  the collector runs on them.

## Next, in order

### 0. The trend chart is empty until the captures accumulate

This is the one thing a demo cannot show today. No source publishes historical
savings rates, so the line appears only after `capture_rates` has run on more
than one day. Nothing to build -- it needs a scheduled task and a week.

Worth deciding while waiting: whether a capture that finds an unchanged board
should still be stored. It currently is, which is correct for a trend, and it
means most days add a point that says nothing.

### 0b. Three banks are still missing, and one aggregator carries everything

Techcombank, ACB and Sacombank appear in no source that renders. And the whole
board comes from one site: if it goes down or changes shape, the dashboard has
nothing, and the BIDV cross-check would report agreement between the one row
it can see and nothing else.

Two ways forward, both real work rather than tuning:

- **A second aggregator** for cross-checking the whole board rather than one
  row. That turns the cross-check from a spot audit into a real one.
- **A bank-by-bank assault** on the nine that resist: their apps' backends,
  their PDFs, or the State Bank's own disclosure filings. Slow, and the only
  path to first-party data.

### 0c. No `.gov.vn` source is scraped yet

Unchanged from before, and it still matters for the macro tab: the
`government` tier is the only one that clears 60 alone, and it has never been
verified because `sbv.gov.vn` never settles and `gso.gov.vn` does not connect.

### 0d. World Bank and IMF disagree on GDP per capita

They differ by 3.8-4.7% in recent years, wider than the 2% two readings of one
quantity are allowed to differ by, so the topic refuses. Either the tolerance
is too tight for economic aggregates with different vintages, or the gap is
itself the result worth showing. That is a calibration decision, not
arithmetic, and it is the project owner's.

### 0e. A source health check that fails loudly

`scoring/health.py` records what worked; nothing probes on a schedule. A check
asserting "more than N rows, newest within a week" per source turns silent rot
into a red test. For rates the check already half exists -- the BIDV
comparison -- and it wants to run whether or not anyone opens the page.

### 0f. Evaluation, and then monitoring

Nothing measures whether a scrape is *right*. For rates the measurable things
are: does the board still parse, does BIDV still match, how many banks came
back. For the macro tab: coverage, freshness, and how often the insight guards
reject a paragraph. Monitoring follows once anything runs unattended; the
numbers already exist.

### 1. A second aggregator, then a scheduled capture

In that order, because a trend built on one source that changes shape is worse
than a short trend built on two that agree. See 0b and 0.

## Not doing, and why

- **Screenshots / vision.** The DOM already carries roles, labels and state,
  and every page this project scrapes is a table. Vision costs far more per
  step and reads numbers less reliably than the DOM hands them over.
- **A general browser agent.** Tried and removed. A source whose steps are
  written down repeats exactly and costs no model calls; a model choosing
  clicks on a rate table adds a failure mode and buys nothing.
- **LLM-as-judge on the scraped numbers.** The cross-check against BIDV's own
  endpoint is arithmetic, and arithmetic cannot be talked into agreeing.
