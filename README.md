# Daily Global-Macro Brief

A free, automated daily news scraper → summarizer → static reading site, built on
the "Meridian pattern": **RSS-first ingestion → SQLite dedup → LLM summarization
(Gemini Flash + fallbacks via LiteLLM) → Jinja2 static site → Cloudflare Pages on a
GitHub Actions cron.** See `Free Daily Global-Macro News Scraper and Summarizer_
Architecture and Toolchain Guide.md` for the full research behind these choices.

## What it does

1. **Ingest** — `feedparser` pulls every feed in `config/feeds.yaml` (English macro
   sources: OilPrice, Investing.com, CNBC, FXStreet, Fed, ECB, Bank of England,
   MarketWatch, Bangkok Post, …).
2. **Dedup** — SQLite, keyed on URL hash + normalized title (near-dup detection).
3. **Extract** — for thin RSS teasers, fetch full text via `trafilatura` →
   `readability-lxml` cascade.
4. **Summarize** — LiteLLM calls the `LLM_CHAIN` (default Cerebras → Groq → Gemini →
   local Ollama), retrying rate-limits before falling through. Output is structured
   JSON: `{headline, bullets[3-5], topic, sentiment, importance(1-5), instruments[]}`.
5. **Cluster** — within each topic, near-duplicate stories from different outlets are
   merged (pure-Python TF cosine on stemmed headlines, no ML deps) into one card with
   an "also covered by" source list. Tunable threshold in `src/cluster.py`.
6. **Render** — Jinja2 builds one page per day: topic nav, importance-sorted stories,
   importance dots, expandable key-takeaways, and the merged-source UI (`site/`).
7. **Deploy** — GitHub Actions cron builds and pushes `site/` to Cloudflare Pages.

## Quick start (local)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env          # then paste your GEMINI_API_KEY

# Dry run — ingest + render only, no LLM/API key needed:
python -m src.pipeline --no-summarize

# Full run (needs a key in .env):
python -m src.pipeline

# Re-render the site from the existing DB:
python -m src.pipeline --render-only
```

Open `site/index.html` in a browser.

## Free LLM keys

- **Gemini (primary):** https://aistudio.google.com/apikey — `GEMINI_API_KEY`
- **Groq (fallback):** https://console.groq.com/keys — `GROQ_API_KEY`
- **Cerebras (fallback):** https://cloud.cerebras.ai — `CEREBRAS_API_KEY`
- **Ollama (local, no key):** `ollama pull qwen2.5` and it's used automatically last.

Any provider with no key set is skipped. The fallback chain and models are
configurable via `LLM_CHAIN` in `.env`. **Free-tier limits change often and free
prompts may be used for training — route confidential content to local Ollama.**

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
   - `GEMINI_API_KEY` (and optionally `GROQ_API_KEY`, `CEREBRAS_API_KEY`)
   - `CLOUDFLARE_API_TOKEN` (Pages:Edit permission)
   - `CLOUDFLARE_ACCOUNT_ID`
4. The cron runs daily at 23:00 UTC (≈ 06:00 Bangkok). Trigger manually anytime via
   the **Run workflow** button (workflow_dispatch). The SQLite DB is cached between
   runs so dedup persists.

## Project layout

```
config/feeds.yaml        feed list (name, url, topic hint)
src/config.py            env + feeds loader
src/models.py            SQLite schema
src/ingest.py            feedparser + dedup
src/extract.py           trafilatura → readability cascade
src/summarize.py         LiteLLM fallback chain → structured JSON
src/render.py            Jinja2 static-site builder
src/pipeline.py          orchestration / CLI entry
templates/, static/      site theme
.github/workflows/       daily cron
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
