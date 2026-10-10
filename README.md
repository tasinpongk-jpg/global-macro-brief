# Daily Global-Macro Brief

A free, automated daily news scraper → summarizer → static reading site, built on
the "Meridian pattern": **RSS-first ingestion → SQLite dedup → LLM summarization
(MiniMax-M2 + Gemini/Mistral fallbacks via LiteLLM) → Jinja2 static site →
Cloudflare Pages on a GitHub Actions cron.** See `Free Daily Global-Macro News Scraper and Summarizer_
Architecture and Toolchain Guide.md` for the full research behind these choices.

## What it does

1. **Ingest** — every feed in `config/feeds.yaml` (English macro sources:
   OilPrice, Investing.com, CNBC, FXStreet, Fed, ECB, Bank of England, MarketWatch,
   Bangkok Post, …) is downloaded with a 20 s timeout and an identifying
   User-Agent (`src/net.py`), then parsed with `feedparser`. Feeds that return
   nothing are reported as a "Feed health" warning on the Actions run.
2. **Dedup** — SQLite, keyed on URL hash + normalized title (near-dup detection).
3. **Extract** — for thin RSS teasers, fetch the page (only if robots.txt allows
   it) and extract full text via a `trafilatura` → `readability-lxml` cascade.
4. **Summarize** — LiteLLM calls the `LLM_CHAIN` (default MiniMax-M2 → Gemini
   2.5 Flash → Mistral Small → local Ollama), 5 articles per request and several
   requests in parallel. Output is structured JSON per article:
   `{headline, bullets[1-5], topic, sentiment, importance(1-5), instruments[]}`.
   A per-run circuit breaker drops providers that fail hard (auth, billing,
   retired model, daily quota) or keep rate-limiting, and stops once every
   provider is exhausted. MiniMax's `<think>` reasoning is stripped before
   parsing, Gemini runs with thinking disabled, and a malformed JSON reply is
   retried once. Articles are retried at most `SUMMARY_MAX_ATTEMPTS` (3) times
   and only within `SUMMARY_MAX_AGE_DAYS` (7); anything not summarized is still
   shown on the site by its feed title ("summary pending").
5. **Cluster** — within each topic, near-duplicate stories from different outlets are
   merged (pure-Python TF cosine on stemmed headlines, no ML deps) into one card with
   an "also covered by" source list. Tunable threshold in `src/cluster.py`.
6. **Render** — Jinja2 builds one page per day: topic nav, importance-sorted stories,
   importance dots, expandable key-takeaways, and the merged-source UI (`site/`).
7. **Deploy** — GitHub Actions cron builds and pushes `site/` to Cloudflare Pages.

## Quick start (local)

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate

# Windows PowerShell (use instead of the two commands above)
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install --only-binary=litellm -r requirements.txt
cp .env.example .env          # then paste your MINIMAX_API_KEY (and/or GEMINI_API_KEY)

# Dry run — ingest + render only, no LLM/API key needed (stories appear by
# feed title, marked "summary pending"):
python -m src.pipeline --no-summarize

# Full run (needs a key in .env):
python -m src.pipeline

# Re-render the site from the existing DB:
python -m src.pipeline --render-only
```

Open `site/index.html` in a browser.

## Tests

The test suite is offline: fake feeds, fake HTTP and a fake LLM provider
(`tests/fakes.py`) drive the whole pipeline against a temporary SQLite database,
so it needs no API keys and makes no network calls.

```bash
pip install --only-binary=litellm -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check .
```

GitHub Actions runs ruff and the tests (Windows + Ubuntu) on every push and pull
request that touches anything other than Markdown/docs.

## LLM keys

- **MiniMax (primary):** https://platform.minimax.io — `MINIMAX_API_KEY`
  (international endpoint `https://api.minimax.io/v1`; override with
  `MINIMAX_API_BASE`). ~100 articles/minute with the default batching.
- **Gemini (fallback):** https://aistudio.google.com/apikey — `GEMINI_API_KEY`.
  The free tier allows only ~20 requests/day (≈100 articles at 5 per request).
- **Mistral (fallback):** https://console.mistral.ai — `MISTRAL_API_KEY`.
- **Ollama (local, no key):** `ollama pull qwen2.5` and it's used automatically
  last (skipped on CI).
- Groq, Cerebras and Cloudflare Workers AI are still supported if you add them to
  `LLM_CHAIN` (Cloudflare needs both `CLOUDFLARE_API_KEY` and
  `CLOUDFLARE_ACCOUNT_ID`).

Any provider with no key set is skipped. The fallback chain, batch size and
parallelism are configurable in `.env` (see `.env.example`). **Free-tier limits
change often and free prompts may be used for training — route confidential
content to local Ollama.**

## Cloud deploy (GitHub Actions → Cloudflare Pages)

**Live site:** https://macro-brief-buy.pages.dev
(The Pages project is named `macro-brief`, but the `macro-brief.pages.dev`
subdomain was already taken, so Cloudflare auto-assigned `macro-brief-buy`.
`*.pages.dev` subdomains are globally unique — the project name and the URL can
differ.)

1. Push this repo to GitHub.
2. Create a Cloudflare Pages project named `macro-brief` (or edit the name in
   `.github/workflows/daily.yml`).
3. Add repo **Secrets** (Settings → Secrets and variables → Actions):
   - `MINIMAX_API_KEY` (primary) and optionally `GEMINI_API_KEY`, `MISTRAL_API_KEY`
   - `CLOUDFLARE_API_TOKEN` (Pages:Edit permission)
   - `CLOUDFLARE_ACCOUNT_ID`
4. The cron is set for 23:00 UTC (≈ 06:00 Bangkok); GitHub usually starts
   scheduled runs 1–3 hours late. Trigger manually anytime via the **Run
   workflow** button (workflow_dispatch).
5. Failure alerts: if a daily run fails — including a summarization outage where
   no article could be summarized (`--strict`) — the workflow opens (or comments
   on) a `daily-run-failure` issue, and closes it after the next good run. The
   site is still deployed with title-only cards in that case.

The SQLite DB persists across runs three ways, in order of use: a fast **Actions
cache**, a durable **`db-snapshot` branch** (auto-restored if the cache is ever
evicted), and a 90-day **artifact** for manual recovery. The `db-snapshot` branch
holds a single gzipped `news.db.gz` and is force-pushed each run — don't merge it.
(Older snapshots held a raw `news.db`; the restore step understands both.)

Keeping the DB small: full article text is only kept until an article has been
summarized, then cleared; the pipeline VACUUMs automatically when ≥20% of the file
is free pages (`python -m src.pipeline --vacuum` forces it). The snapshot push is
size-guarded (skipped with a warning above 90 MB compressed) and non-fatal, and
the Cloudflare deploy runs whenever a site was built — a backup problem can never
leave the live site stale again.

## Project layout

```
config/feeds.yaml        feed list (name, url, topic hint)
src/config.py            env + feeds loader, default LLM chain
src/models.py            SQLite schema, migrations, compaction
src/net.py               shared HTTP: User-Agent, timeouts, robots.txt
src/ingest.py            feed download + feedparser + dedup
src/extract.py           trafilatura → readability cascade
src/summarize.py         LiteLLM chain, circuit breaker, batching → JSON
src/digest.py            daily "mood" line
src/cluster.py           cross-source story clustering
src/render.py            Jinja2 static-site builder
src/pipeline.py          orchestration / CLI entry
templates/, static/      site theme
.github/workflows/       daily cron + alerting, tests + lint
tests/                   offline test suite (fakes.py = fake feeds/HTTP/LLM)
```

## Roadmap (from the architecture guide)

- **Semantic clustering** — the current clustering is lexical (stemmed-headline TF
  cosine); it catches near-identical headlines but misses heavy paraphrases. Upgrade
  to embeddings (a free embedding API, or Meridian-style UMAP/HDBSCAN) for
  meaning-based merging across very differently-worded reports.
- **Thai sources** — Krungthep Turakij / Prachachat / Thansettakij via RSSHub;
  summarize with Typhoon 2 for highest Thai fidelity.
- **No-RSS sources** — OPEC, Reuters/Bloomberg headlines via self-hosted RSSHub.
- **GDELT** — broad geopolitical/macro net filtered by keywords.

## Legal

Personal, non-commercial. Stores only summaries + links (not reposted full text);
respects robots.txt; attributes and links every source. Don't republish licensed
(Bloomberg/Reuters/FT) content — summarize and link.
