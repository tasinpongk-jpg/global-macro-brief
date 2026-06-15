# Building a Free, Daily Global-Macro News Scraper + Summarizer + Reading Site

## TL;DR

- **Build the “Meridian pattern”: RSS-first ingestion (feedparser) + trafilatura for the few sites needing scraping → SQLite dedup → batch-summarize with Google Gemini Flash (1,500 req/day free) as primary and Groq Llama-3.1-8b-instant (14,400 req/day, 500K tokens/day free) as fallback → render static HTML → deploy free to Cloudflare Pages on a GitHub Actions cron.** This is entirely free and matches skills you already have.
- **Don’t reinvent the architecture — fork or study `iliane5/meridian` (2.4k stars / 434 forks, Gemini Flash-powered, RSS→LLM→clustered briefs).** For a reading UI you can self-host today, pair FreshRSS or Miniflux with an AI-summary add-on; for Thai-language summaries, Gemini Flash and Qwen2.5 handle Thai well, and SCB 10X’s Typhoon 2 is a Thai-specialist fallback.
- **The binding constraint on free LLM tiers is tokens-per-day, not requests.** Gemini Flash (1,500 req/day, 250K tokens/min) is the most generous single free backend for this job; Groq and Cerebras (1M tokens/day) are strong, fast complements. For truly unlimited volume, run Ollama locally with Qwen2.5 or Llama 3.3.

## Key Findings

### 1. Best existing open-source projects to start from

- **Meridian (`iliane5/meridian`, 2.4k stars / 434 forks as of June 2026)** is the closest match to your goal: it scrapes hundreds of RSS sources, extracts content, runs Gemini for per-article analysis, clusters with embeddings (UMAP/HDBSCAN), and generates a daily “intelligence brief.” Stack: TypeScript/Hono, PostgreSQL/Drizzle, Cloudflare Workers/Pages, Nuxt frontend, Python for the briefing step.  The README is explicit about why this is free to run: *“Gemini 2.0 Flash: The true unsung hero of this project — blazing fast, dirt cheap, and surprisingly capable when prompted well… But Flash isn’t just a time-saver — it’s the engine that makes Meridian possible at all.”* Caveat: brief generation is a manual Python notebook (not fully automated),  and it uses PostgreSQL not SQLite.
- **`lfzawacki/meridiano`** is a simpler Python/Flask reimplementation of Meridian — SQLite-friendly, LiteLLM-based (so any LLM backend), cron-driven, with a clean web UI.  Probably a better base for you than the original.
- **`finaldie/auto-news`** — mature personal aggregator, LLM via LangChain (ChatGPT/Gemini/Ollama), sources include RSS/Reddit/YouTube. 
- **`Thysrael/Horizon`** — AI news radar, scores items 0-10 with many backends  (Claude/GPT/Gemini/DeepSeek/Ollama), supports OpenBB financial watchlists, publishes to GitHub Pages, has a finance category config out of the box.
- **`georgejieh/freshrss-ai-summarizer`** — purpose-built for analysts: pulls from FreshRSS, summarizes with OpenAI or local Ollama, does bullish/bearish sentiment and market-impact summaries.
- Curated list: **`taielab/awesome-ai-news`** catalogs these plus FeedCraft (Go RSS generator with AI), RSS-Master, CloudFlare-AI-Insight-Daily (Gemini + GitHub Pages), and Hextra/Hugo static-site publishers.

### 2. RSS readers & feed generation

- **FreshRSS** (PHP, SQLite-capable, ~9.4k stars, very active) — easiest start, web setup wizard, extensions, WebSub, Google Reader API for mobile. Best if you want a flexible reading UI now.
- **Miniflux** (Go, single binary, PostgreSQL-only, minimalist) — lighter, faster, privacy-focused, built-in full-text fetch, regex filters; great as a clean reader.
- **RSSHub** (`DIYgod/RSSHub`, ~38,800 stars / 8.5k forks, 1,000+ routes) — generate RSS for sites that don’t offer it (Twitter/X, Telegram, YouTube, many news sites). Self-host via Docker (`diygod/rsshub:chromium-bundled` for JS-rendered pages) + Redis cache. This is your tool for no-RSS sources.

### 3. News scraping frameworks — maintained vs abandoned (2025/2026)

- **trafilatura** (`adbar/trafilatura`) — ACTIVELY maintained, best balanced accuracy among open-source tools (F1 0.945 ± 0.009, precision 0.925, recall 0.966 in ScrapingHub’s article-extraction-benchmark), multilingual, pure-Python, no browser. Used by SCB’s Typhoon team to build their Thai corpus.  **Use this as your primary extractor.**
- **newspaper3k** — effectively ABANDONED (no release since ~2018/2020). Don’t use.
- **newspaper4k** — the actively-maintained fork; backward-compatible, multithreaded, Google News integration, 80+ languages.  Use if you want newspaper’s metadata/NLP convenience (note: 180+ open issues, dependency-heavy setup).
- **news-please** (`fhamborg/news-please`) — maintained, good for large-scale/CommonCrawl archival, combines scrapy + newspaper + readability.
- **Fundus** — highest precision (F1 ~0.97) but only supports predefined publishers. 
- **feedparser** — the standard Python RSS/Atom parser; still the backbone for ingestion.
- None handle JS-heavy sites natively — pair with Playwright (which you already use) as the final fallback. A robust cascade: **trafilatura → readability-lxml → newspaper4k → Playwright.**

### 4. News sources for global macro

**Free native RSS (confirmed working):**

- **OilPrice.com**: `https://oilprice.com/rss/main` (energy/oil)
- **Investing.com**: `https://www.investing.com/rss/news.rss`  (+ category feeds for commodities, forex, economy; see investing.com/webmaster-tools/rss)
- **CNBC**: per-topic feeds at cnbc.com/rss-feeds (incl. cnbc.com/oil-gas)
- **MarketWatch**: via Dow Jones feeds (feeds.content.dowjones.io)
- **Federal Reserve**: federalreserve.gov/feeds/feeds.htm (press releases, monetary policy)
- **ECB**: ecb.europa.eu/home/html/rss.en.html (press releases, speeches)
- **Kitco** (gold/precious metals): kitco.com/news
- **FXStreet**, **Seeking Alpha**, **Yahoo Finance**, **Nasdaq**, **MoneyControl**, plus Financial Stability Board, Bank of Canada, SNB, RBNZ, Riksbank.
- Feedspot maintains curated category lists (financial, commodity, oil & gas, central banks) — a fast way to harvest feed URLs.

**Need scraping or RSSHub (no reliable free RSS):**

- **Bloomberg** and **Reuters** — historically had RSS but now restrict/deprecate; treat as scrape-or-RSSHub. **OPEC** — no robust official news RSS; scrape press releases or use RSSHub. **ZeroHedge** — has a feed but is volatile. **Financial Times** — paywalled.

**Free news APIs (compare):**

- **GDELT Project** — completely free, effectively unlimited, 100+ countries/languages, 15-min updates, CAMEO event coding + tone/sentiment + Global Knowledge Graph. Best for geopolitical/macro signal at scale. Downside: research-grade, no full article text, steep learning curve. DOC API: `https://api.gdeltproject.org/api/v2/doc/doc`.
- **Marketaux** — finance-specific, ~100 req/day free, tags articles with tickers + sentiment (-1 to 1). Good for oil/gold ticker-linked news.
- **NewsData.io** — 500 req/day free (10 articles/req), multilingual, commercial use allowed on free tier.
- **The Guardian Open Platform** — 5,000 calls/day free (one high-quality publisher).
- **NewsAPI.org** — only 100 req/day, dev-only (no commercial use), no full text on free tier. Weakest option.
- **GNews** — 100 req/day free. **Finnhub** — free company/market news endpoint. **Alpha Vantage** — free news+sentiment endpoint (useful for macro tickers). **Mediastack** — free tier delayed 30 min, no history.

**Thai news:**

- **Bangkok Post** offers native RSS (breaking news, top stories, and a Business section at bangkokpost.com/business) — English, the cleanest Thai-market English source.
- **Thai PBS World** (world.thaipbs.or.th) — English service of the public broadcaster.
- Thai-language business dailies (Krungthep Turakij, Prachachat under Nation Group; Thansettakij) carry deep market/macro coverage; many lack clean RSS → use RSSHub or scrape with trafilatura. The Stock Exchange of Thailand and InfoQuest/ThaiPR (set.or.th, ThaiPR.net) are primary-source options for Thai market data.

### 5. Free-tier LLMs for daily summarization load (2026)

**The binding constraint is tokens-per-day (TPD), not requests-per-day.** A daily run summarizing 100–300 articles at ~1–3K input tokens each can run into low-hundreds-of-thousands of tokens.

- **Google Gemini (AI Studio free tier)** — **best single free backend.** Per Google’s official rate-limits docs (ai.google.dev/gemini-api/docs/rate-limits, updated 2026-05-28), free-tier Flash gives **~1,500 requests/day** and **10 RPM** (Gemini 3 Flash) at **250,000 tokens/min**; Flash-Lite runs 15 RPM. Free covers Flash and Flash-Lite only (Gemini 3 Flash, 3.1 Flash-Lite, 2.5 Flash/Flash-Lite); **Pro models were removed from the free tier in April 2026** (the 3.1 Flash-Lite GA rollout on May 7, 2026 further cut Pro free RPD 100→50). RPD resets at midnight Pacific (“Requests per day (RPD) quotas reset at midnight Pacific time… Rate limits are applied per project, not per API key”). Caveats: free-tier prompts may be used to train Google’s models (don’t send confidential SET data); Google cut free quotas significantly in Dec 2025, so re-verify; note Gemini 2.0 Flash (the model Meridian used, with its 1M TPM) was shut down June 1, 2026. You already use Gemini — it’s the obvious primary.
- **Groq free tier** — extremely fast (LPU, 300–1,000+ tok/s). Per-model caps verified ~June 4, 2026: **llama-3.3-70b-versatile = 30 RPM / 1,000 RPD / 12K TPM / 100K TPD**; **openai/gpt-oss-120b = 30 RPM / 1,000 RPD / 8K TPM / 200K TPD**; **llama-3.1-8b-instant = 30 RPM / 14,400 RPD / 6K TPM / 500K TPD** (the outlier, and the origin of the “14,400/day” figure online). The “1,000 vs 14,400 RPD” confusion is resolved: **1,000 is the standard cap; 14,400 applies specifically to llama-3.1-8b-instant.** For free batch summarization, **llama-3.1-8b-instant is the best Groq pick** (500K TPD — the most generous). Groq’s Batch API is a paid (Developer-tier) feature, not free.
- **Cerebras free tier** — **1,000,000 tokens/day free**, no card, ultra-fast (2,000+ tok/s); 30 RPM, ~8K context cap on free tier. Highest free *daily token budget* of any single provider — excellent batch complement.
- **OpenRouter** — free model slots but only **20 RPM / 50 req/day** unless you hold ≥$10 credit (then 1,000/day). Useful as model-diversity fallback, not primary.
- **GitHub Models** — free, rate-limited (~10 RPM / 50 RPD for free accounts) — testing only.
- **Cloudflare Workers AI** — 10,000 “neurons”/day free; convenient if you’re already on Cloudflare.
- **Mistral** — free tier (~1B tokens/month on open models) with its own models.
- **Together AI / Fireworks / SambaNova** — mostly small signup credits, not durable free tiers.
- **Local / Ollama (zero-cost, unlimited)** — **Qwen2.5 (7B/14B/32B)** — strong multilingual incl. Thai;  **Llama 3.3 70B** (needs ~48GB VRAM/unified memory) or **Llama 3.1 8B** (6GB)  — best general; **Gemma 3** (140+ languages).  Tradeoff: needs local compute (you have admin rights/local machine), slower than Groq/Cerebras, but no rate limits and fully private — ideal for confidential SET-adjacent content.

### 6. Frontend / hosting (all free)

- **Static-site + GitHub Actions cron + Cloudflare Pages** is the cleanest free, automated pattern. Cloudflare Pages: unlimited bandwidth, free TLS, custom domains,  500 builds/month, deploy any static folder via `cloudflare/wrangler-action@v3`. You’ve used Quarto + Cloudflare Pages — that works perfectly here.
- **Scheduling:** GitHub Actions `schedule: cron` runs your Python pipeline daily on a free ubuntu runner,  generates HTML, and either deploys via wrangler or pings a Cloudflare build hook. Alternative: run the pipeline on your local machine via cron (better if you use local Ollama and want zero cloud-LLM dependency) and `wrangler pages deploy`.
- **Generators:** Quarto (you know it), Hugo (fast, native Cloudflare guide exists), Next.js (you know it; static export), or a tiny Jinja2 + Python script (full control over the “headlines vs. key points” layout).
- **Free hosts:** Cloudflare Pages (recommended), GitHub Pages (simplest, but repo public unless Pro),  Vercel, Netlify.
- **Reading UI structure:** group by topic (Energy/Oil, Gold/Metals, Central Banks, Geopolitics, Thai Markets). Per story show: bold headline + source + timestamp as the scannable layer; an expandable 3–5 bullet “key takeaways” block beneath; link out to original. This mirrors what Meridian and the FreshRSS summarizer produce.

## Details

### Recommended end-to-end architecture

1. **Ingestion (hybrid):** A YAML/JSON list of feeds → `feedparser` for all native RSS (Fed, ECB, OilPrice, Investing.com, CNBC, Kitco, Bangkok Post, etc.). For no-RSS sources (OPEC, Reuters/Bloomberg headlines, Thai-language dailies) → self-hosted **RSSHub** routes, falling back to **trafilatura** (then Playwright) for full-text extraction. GDELT DOC API as a broad geopolitical/macro net, filtered by your keywords (OPEC, crude, WTI, Brent, gold, Fed, rate, etc.).
1. **Dedup + storage:** SQLite. Store URL hash + title + normalized title (for near-dup detection) + published time + source + raw text + summary JSON. UNIQUE index on URL hash; optionally embeddings + cosine for cross-source dedup of the same story.
1. **Summarization:** Batch the day’s new articles. Primary = **Gemini Flash** (structured JSON output: `{headline, 3-5 bullets, topic, sentiment, instruments_affected}`). On 429/quota, fall back to **Groq llama-3.1-8b-instant**, then **Cerebras**, then **local Ollama/Qwen2.5**. Use LiteLLM to abstract providers (meridiano already does this). Keep prompts tight and cap `max_tokens` to protect TPD.
1. **Render + deploy:** Python/Jinja2 (or Quarto) generates one static page per day plus an index, grouped by topic with the headline/key-points layout. GitHub Actions cron (e.g. `0 23 * * *` UTC ≈ early morning Bangkok) builds and deploys to Cloudflare Pages.
1. **Read:** clean static site; optionally also pipe summaries back into FreshRSS/Miniflux for mobile reading.

### Gotchas

- **Rate limits change fast** — re-check Gemini/Groq/Cerebras limits at build time; implement exponential backoff + provider fallback. TPD (not RPD) is what kills batch jobs; Groq’s exact org-level numbers require login at console.groq.com/settings/limits.
- **RSS reliability** — feeds break, rename, or rate-limit; cache last-good, log failures, and don’t hard-fail the run on one dead feed.
- **Thai-language summarization** — Gemini Flash and Qwen2.5 handle Thai well; for highest Thai fidelity use **Typhoon 2** (SCB 10X, Apache-2.0, on Hugging Face/ opentyphoon.ai), purpose-built for Thai and benchmarking on par with much larger models for Thai tasks. Consider summarizing Thai sources in Thai, or translating to English in the same LLM call.
- **ToS / legal** — prefer RSS/APIs (you confirmed this). For scraping: respect robots.txt and rate limits, store only summaries + links (not full reposted text) on your public site, attribute sources, keep the site personal/non-commercial. Bloomberg/Reuters/FT content is licensed — summarize and link, don’t republish.
- **Free-tier privacy** — Gemini/Groq free tiers may use prompts for training; route anything sensitive to local Ollama.

## Recommendations

1. **Stage 1 (this weekend):** Stand up FreshRSS (Docker, SQLite) + the global-macro feed list above + `georgejieh/freshrss-ai-summarizer` pointed at Gemini Flash. You get a working read+summarize loop in hours, validating sources and prompt quality before building anything custom.
1. **Stage 2:** Fork **`lfzawacki/meridiano`** (Python/Flask/SQLite/LiteLLM) as your pipeline skeleton. Swap in your feeds, add RSSHub for no-RSS and Thai sources, wire LiteLLM to a Gemini→Groq→Cerebras→Ollama fallback chain. Run it locally via cron first.
1. **Stage 3:** Replace its Flask UI with a static generator (Quarto or Jinja2) + Cloudflare Pages + GitHub Actions cron for a zero-maintenance public reading site with the headline/key-points layout.
1. **Stage 4 (optional):** Add embedding-based clustering (like Meridian) to merge duplicate stories across sources and produce a true daily “macro brief,” and add Typhoon 2 for Thai.

**Thresholds that change the plan:** If your daily volume pushes past Gemini’s ~1,500 req/day or you hit TPD walls across providers, move bulk summarization to **local Ollama** (unlimited, private) and reserve cloud LLMs for the final brief. If you need confidential handling of SET-related material, go local-first from the start.

## Caveats

- LLM free-tier numbers (Gemini, Groq, Cerebras) change frequently; figures here are mid-2026 and should be re-verified at the provider console/docs before you rely on them. Groq’s per-model table requires login for exact org-level numbers, and Gemini cut free quotas in Dec 2025 and again restructured in April–May 2026.
- Some “free RSS” for major outlets (Reuters, Bloomberg) has been quietly deprecated; verify each feed URL resolves before adding it.
- Star counts and last-commit recency for GitHub projects move; Meridian was 2.4k stars / 434 forks and meridiano is a smaller community fork — check current activity before committing.
- This report assumes personal, non-commercial use; redistributing summarized paywalled content publicly carries legal risk regardless of the tech.