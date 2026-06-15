# Free AI/LLM API Providers with Usage Tiers — Complete 2026 Guide
### For a Bangkok-based Python / TypeScript developer (you already have Grok/xAI + Cerebras)

## TL;DR
- **The most generous perpetual free tiers (no credit card, OpenAI-compatible, usable from Thailand) are: Cerebras (~1,000,000 tokens/day), Mistral La Plateforme (~1 billion tokens/month), Groq (14,400 req/day on Llama 3.1 8B), Google AI Studio/Gemini (free Flash + Gemma), Cloudflare Workers AI (10,000 neurons/day), and NVIDIA NIM (40 RPM across 100+ models).**
- **For the single highest-leverage move: drop a one-time $10 into OpenRouter to permanently unlock 1,000 requests/day across ~28 `:free` models through one key.** Mistral's ~1B tokens/month is the largest total allowance; Cerebras has the biggest no-card daily *token* bucket.
- **Easiest "no credit card, start in minutes" picks:** Groq, Cerebras, Google AI Studio, NVIDIA NIM, GitHub Models, Cloudflare, SambaNova ($5), Z.ai GLM-Flash, Mistral. Chinese first-party APIs (Qwen/DashScope, Z.ai, DeepSeek, Kimi) are fully accessible from Bangkok and often give the best APAC latency.

## Key Findings

### Tier S — Perpetual free, high daily volume, no credit card (start here)
All OpenAI-compatible; allowances reset (not one-time credits).

| Provider | Free allowance (binding caps) | Key free models | Card? | Notes |
|---|---|---|---|---|
| **Cerebras** | **30 RPM · 60,000–100,000 TPM · 1,000,000 tokens/day**; temporary 8,192-token context cap | gpt-oss-120b, Llama 3.3 70B, Qwen-3-235B, Qwen-3-32B, Llama 4 Scout; GLM-4.7 (10 RPM/100 RPD) | No | Fastest inference (~2,600 tok/s on Llama 4 Scout, WSE-3 hardware). You already use this. |
| **Groq** | Per model: **Llama 3.1 8B = 14,400 req/day + 500,000 TPD**; bigger models = 1,000 req/day (Llama 3.3 70B: 30 RPM/12K TPM/100K TPD; gpt-oss-120b: 8K TPM/200K TPD) | Llama 3.1/3.3, gpt-oss 20b/120b, Qwen3-32B, Kimi K2, Whisper | No | Sub-200ms latency. **Does NOT train on your data.** Token/day caps bind first. |
| **Google AI Studio (Gemini)** | Dynamic per-project (see Details); ~250,000 TPM shared | Gemini 2.5/3/3.5 Flash, 3.1 Flash-Lite, 2.5 Pro, Gemma 4 | No | **Data IS used for training** on free tier. Available in Thailand. Free tier may NOT serve EU/UK users. |
| **NVIDIA NIM (build.nvidia.com)** | 40 RPM; 1,000 inference credits at signup (up to 5,000) | DeepSeek, Kimi, GLM-5.1, gpt-oss, Llama, Nemotron, Qwen — 100+ | No | Phone verification. Hosted-endpoint prompts are logged/used for training. |
| **Cloudflare Workers AI** | **10,000 Neurons/day** (~100–300 text generations); resets 00:00 UTC | Llama 3.1/3.3, Qwen3, Gemma 4, DeepSeek R1 distill, Kimi K2.5 | No | Then $0.011/1,000 Neurons on Workers Paid. Edge inference, 300+ locations. |
| **OpenRouter** | 20 RPM; **50 req/day**, or **1,000 req/day after one-time $10 lifetime top-up** (shared across free models) | DeepSeek, Llama 3.3 70B, Qwen3-Coder, GLM-4.5-Air, gpt-oss, Kimi | Card to top up | One key → ~28 `:free` models. Free routes may log data. |
| **GitHub Models** | ~10 RPM/50 RPD (high-tier); ~15 RPM/150 RPD (low-tier); 8K in / 4K out per request | GPT-5, GPT-4.1, o-series, Llama, DeepSeek, Mistral, Grok 3 | No (GitHub acct) | Frontier *closed* models free, but tiny caps — testing only. |

### Tier A — Big monthly grants / generous free, no card
| Provider | Free allowance | Models | Card? |
|---|---|---|---|
| **Mistral La Plateforme** | **~1 billion tokens/month** ("Experiment" plan); **2 RPM · 500,000 TPM** | Mistral Small/Medium/Large, Codestral, Pixtral, Nemo | No (phone verification) |
| **SambaNova Cloud** | $5 credit + standard free-tier rate limits, very fast inference | DeepSeek V3.1/V3.2, Llama 3.3/4, gpt-oss-120b, gemma-3 | No |
| **Z.ai (Zhipu GLM)** | Permanent free models | GLM-4.7-Flash (203K ctx), GLM-4.5-Flash, GLM-4.6V-Flash | No |
| **Cohere** | 1,000 API calls/month (20 RPM chat) | Command A/R/R+/R7B, Embed 4, Rerank 3.5 | No (trial key) — **non-commercial only** |
| **Hugging Face Inference Providers** | $0.10/month credits free ($2/month on Pro $9) | Routes to Together, Fireworks, Novita, Nebius, etc. | No |

### Tier B — One-time signup credits (trial → pay-as-you-go)
| Provider | Credit | Notes |
|---|---|---|
| **DeepSeek** | 5M tokens (~$8.40), expires 30 days | Cheapest paid afterward (V4 Flash ~$0.14/$0.28). OpenAI- AND Anthropic-compatible. |
| **Together AI** | $1–$25 signup + 80+ free models | 200+ models; OpenAI-compatible |
| **Alibaba Qwen / DashScope** | 1M tokens/model (~70M total), 90 days, **Singapore region only** | Best APAC latency; OpenAI- & Anthropic-compatible |
| **Kimi / Moonshot** | Small grant; $5 recharge → $5 voucher | OpenAI- & Anthropic-compatible |
| **Fireworks AI** | $1 credit | Fast open-model inference |
| **Nebius** | $1 credit | 60+ models, EU |
| **Nscale** | $5 credit | EU-sovereign (Norway), "no rate limits" |
| **Scaleway Generative APIs** | 1,000,000 free tokens | EU |
| **Hyperbolic / Novita / Baseten / AI21 / Upstage / NLP Cloud** | $1 / $0.50 / $30 / $10 / $10 / $15 | Various open models |

### Specialty / other
- **OVHcloud AI Endpoints** — permanent free **anonymous** tier: **2 requests/minute per IP per model**, NO signup or key required (just omit the key); 40+ open models, OpenAI-compatible, EU-hosted/GDPR. Authenticated key raises it to **400 RPM per project per model** (pay-as-you-go; new Public Cloud accounts get up to $200 trial).
- **Chutes AI** — decentralized (Bittensor); ~200 req/day free after a one-time $5 deposit (the no-deposit free tier was discontinued; cheapest current entry $3/month). OpenAI-compatible.
- **Perplexity** — Pro ($20/mo) includes ~$5/month of API (Sonar) credits; no standalone perpetual free API tier.
- **AI/ML API (aimlapi.com), GMI Cloud** — trial credits; OpenAI-compatible aggregators.

### No free API tier (confirmed)
- **Anthropic Claude** — no perpetual free API tier; occasional expiring $5 trial credit only.
- **OpenAI** — no perpetual free tier; small expiring trial credits; treat production as paid.

## Details

### Ranked by generosity of free usage (highest first)
1. **Mistral La Plateforme — ~1B tokens/month**, no card. Largest total allowance by far, but throttled to 2 RPM / 500K TPM, so it's ideal for batch text processing (summarization, translation, extraction) rather than bursty real-time traffic. A real-world user reported using only ~30K–80K tokens/day against it — i.e. you'd use <0.25% of the quota.
2. **Cerebras — ~1,000,000 tokens/day**, perpetual, no card. Biggest no-card *daily token* bucket and the fastest inference. Trade-off: 8K context cap on the free tier — keep prompts short. Great for high-volume classification/extraction.
3. **Groq — 14,400 req/day on Llama 3.1 8B (500K TPD)**; larger models drop to 1,000 req/day with tight token/day caps. Unbeatable speed and no training on your data.
4. **Google AI Studio / Gemini** — historically the most generous (Flash was 1,500 RPD) but cut 50–80% in Dec 2025 / April 2026; now dynamic per-project (see below).
5. **NVIDIA NIM** — 40 RPM with no hard daily token cap on many models; widest free *frontier-open-weight* catalog.
6. **Cloudflare Workers AI** — 10,000 neurons/day (~100–300 generations).
7. **OpenRouter** — 1,000 req/day (after $10 lifetime top-up) across ~28 free models, one key.

### Google Gemini free-tier limits — important clarification
Google **no longer publishes a fixed per-model RPM/TPM/RPD table** for the free tier (official rate-limits page last updated 2026-05-28). Limits are now **dynamic and per-project**, viewable only in your AI Studio dashboard at **aistudio.google.com/rate-limit**. The conflicting figures online (1,500 vs 250 vs 20 RPD for Flash) are **stale snapshots** from different points across Dec 2025–May 2026, after Google cut free quotas by 50–80%. (The "1,500 RPD" that still appears officially refers to Google *Search grounding* quota, not model requests — a common source of confusion.)

What IS official (pricing page, updated 2026-06-09): **Gemini 2.5 Flash, 2.5 Flash-Lite, 2.5 Pro, 3 Flash Preview, 3.5 Flash, 3.1 Flash-Lite, and Gemma 4 are all free-of-charge** on the free tier; **Gemini 3.1 Pro Preview is paid-only**; all share a ~250,000 TPM cap. No credit card; **data IS used to improve Google's products on the free tier — do not send confidential SET data.** Available in Thailand and across APAC. The free tier may NOT be used to serve users in the EU/EEA/Switzerland/UK (paid tier required there).

### API compatibility (Python / Node.js)
Nearly every provider is OpenAI-compatible — point the OpenAI SDK at their `base_url` and swap the key:
- Groq: `https://api.groq.com/openai/v1`
- Cerebras: `https://api.cerebras.ai/v1`
- Gemini (OpenAI-compat): `https://generativelanguage.googleapis.com/v1beta`
- NVIDIA NIM: `https://integrate.api.nvidia.com/v1`
- OpenRouter: `https://openrouter.ai/api/v1`
- Mistral: `https://api.mistral.ai/v1`
- DeepSeek: `https://api.deepseek.com/v1` (Anthropic-compat at `/anthropic`)
- Together: `https://api.together.xyz/v1`
- SambaNova: `https://api.sambanova.ai/v1`
- Qwen/DashScope: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- Z.ai: `https://open.bigmodel.cn/api/paas/v4` (also Anthropic-compat)
- Kimi/Moonshot: `https://api.moonshot.ai/v1`
- OVHcloud: `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`
- Cohere: `https://api.cohere.com/v2` (plus an OpenAI-compat endpoint)
- Hugging Face router: `https://router.huggingface.co/v1`

GitHub Models (`https://models.github.ai/inference`) and Cloudflare Workers AI are OpenAI-compatible too.

### Notable restrictions
- **Trains on your inputs:** Google AI Studio free tier, NVIDIA NIM hosted endpoints, Mistral free Experiment tier, and most "free model" routes (OpenRouter free, DeepSeek unless opted out). **Groq explicitly does NOT train on your data.**
- **Commercial use:** Cohere trial key is **non-commercial only**. Most others permit commercial use within rate limits.
- **Geography (Bangkok):** Every Tier-S provider works in Thailand. Qwen/DashScope free quota is **Singapore region only** (`dashscope-intl…`). DeepSeek, Kimi, Z.ai, Qwen are Chinese first-party services — fully reachable from Thailand and usually lowest-latency for APAC. (US federal/enterprise DeepSeek bans don't apply to you, but check SET's own data-governance policy before sending any market data.)

## Recommendations

**Stage 1 — Sign up today (all no-card, ~15 min total) and add to your provider rotation:**
1. **Groq** — pairs with your existing Cerebras as a second fast, high-daily-volume workhorse (and it doesn't train on your data).
2. **Google AI Studio (Gemini)** — for long context (Flash 1M-token window) and multimodal; check your live limit at aistudio.google.com/rate-limit.
3. **NVIDIA NIM** — widest free model catalog (DeepSeek, GLM-5.1, Kimi, Qwen, gpt-oss) through one key.
4. **OpenRouter** — one key, ~28 free models; **spend $10 once to lock in 1,000 req/day forever** — the single highest-leverage move on this list.

**Stage 2 — Add for volume/variety:**
5. **Mistral La Plateforme** (~1B tokens/month) for batch text pipelines.
6. **Cloudflare Workers AI** (if already on Cloudflare) and **GitHub Models** (free GPT-5/o-series for low-volume testing).
7. **Qwen/DashScope** (Singapore region) + **Z.ai GLM-4.7-Flash** for best APAC latency and strong bilingual models.

**Stage 3 — Trial credits when you need a specific model or a cheap paid fallback:**
8. **DeepSeek** (5M free tokens, then the cheapest paid API) and **Together** ($1–25) for one-off evaluations.

**Architecture advice:** Put everything behind a router with fallback (LiteLLM, or OpenRouter's auto-router) so a 429 on one free quota fails over to the next provider. Track token/day caps yourself — Groq does not expose RPD in response headers. For any workload touching SET/proprietary market data, restrict to providers that don't train on inputs (Groq, or paid tiers) or self-host.

**Thresholds that should change your choice:**
- Hitting 429s more than once per session, or needing >1,000 sustained req/day per provider → move that workload to **DeepSeek or Qwen paid** (cheapest) or a paid tier.
- Need a hard data-privacy guarantee → **Groq free**, or any **paid tier** (paid tiers at Google/Mistral/DeepSeek don't train on data).
- Need frontier-reasoning quality for free → **GitHub Models** (GPT-5/o-series) is the only no-cost route, but only at low volume.

## Caveats
- **Free tiers change constantly.** Google removed its public limit table; Alibaba killed its standing free Qwen API tier (April 15, 2026), leaving only a 90-day trial; Chutes removed its no-deposit free tier. **Verify the live number in each provider's dashboard before building.**
- **Figures here come from community aggregators (`cheahjs/free-llm-api-resources`, `mnfst/awesome-free-llm-apis`) cross-checked against official provider docs as of June 2026.** Many per-model caps are dynamically adjusted.
- **"Requests/day" ≠ usable capacity** — token/minute and token/day caps usually bind first (e.g., Groq gpt-oss-120b ≈ ~100 calls/day before its 200K TPD cap, not 1,000; Cerebras' 1M TPD is the real ceiling, not request count).
- **Data governance:** As an SET analyst, assume every free tier may train on your inputs unless it explicitly says otherwise — keep confidential market/customer data off free tiers entirely.