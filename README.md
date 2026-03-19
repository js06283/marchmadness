# March Madness Bracket Generator

This repo contains a Python script that uses the OpenAI Responses API to generate March Madness brackets, plus a local/deployable site to compare and score the saved outputs.

It also supports a pure heuristic simulator that uses seed-based win probabilities and a favorite-threshold policy, so you can generate cheap baseline brackets in the same JSON format without calling the API.

## Generator behavior

The generator can:

1. Run GPT-based bracket generation with web-enabled research.
2. Run a heuristic simulator with no API usage.
3. Save bracket files in a format the visualizer can score.

By default, each GPT bracket now performs its own research call before bracket generation. If you want to reuse an older research artifact instead, pass `--skip-research --research-file ...`.

That matters because web search has a per-tool-call charge, while plain model generations are much cheaper. As of March 19, 2026, OpenAI's pricing page shows:

- `gpt-5-mini`: $0.25 / 1M input tokens and $2.00 / 1M output tokens.
- Web search: $10 / 1K calls plus search content tokens billed at model rates.
- Batch API: 50% off inputs and outputs for asynchronous jobs.

Sources:

- [OpenAI pricing](https://openai.com/api/pricing/)
- [OpenAI models guide](https://developers.openai.com/api/docs/models)
- [OpenAI tools guide](https://platform.openai.com/docs/guides/tools)

## Requirements

- Python 3.9+
- `OPENAI_API_KEY` in your environment

## Usage

```bash
export OPENAI_API_KEY=your_key_here
python3 generate_brackets.py --year 2026 --gender mens --count 10
```

Files are written to [`/Users/jxshix/Documents/marchmadness/final_output`](/Users/jxshix/Documents/marchmadness/final_output) by default.

To use the transcribed 2026 men's bracket field:

```bash
python3 generate_brackets.py \
  --year 2026 \
  --gender mens \
  --field-file /Users/jxshix/Documents/marchmadness/field-2026-mens.json \
  --count 10
```

To generate heuristic-only brackets with no API calls:

```bash
python3 generate_brackets.py \
  --generator heuristic \
  --year 2026 \
  --gender mens \
  --field-file /Users/jxshix/Documents/marchmadness/field-2026-mens.json \
  --count 10
```

## Useful flags

```bash
python3 generate_brackets.py --help
```

Important ones:

- `--count 20` to generate more brackets.
- `--generator heuristic` to generate brackets from the seed-based simulator only.
- `--generator both` to emit both GPT and heuristic brackets in one run.
- `--gpt-workers 4` to parallelize GPT bracket generation calls.
- `--output-tag balanced` to make saved filenames easier to identify during parameter sweeps.
- `--gender womens` for the women's tournament.
- `--field-file /Users/jxshix/Documents/marchmadness/field-2026-mens.json` to lock in the official bracket structure.
- `--skip-research --research-file output/research-....json` to reuse a saved research file instead of doing per-bracket research calls.
- `--research-model gpt-5-mini --bracket-model gpt-5-mini` keeps both phases on the lower-cost model.
- `--favorite-threshold-round64 8` and the later-round threshold flags to control when the simulator strongly biases toward the favorite.
- `--seed 42` to make heuristic runs reproducible.

## Output format

The script saves:

- one `research-*.json` file with the field, notes, and sources
- one `brackets-gpt-*.json` file when GPT generation runs
- one `brackets-heuristic-*.json` file when heuristic generation runs

Each bracket includes picks by round for each region plus the Final Four, title, and summary.

## Notes

- The script asks the model to return strict JSON, but model output can still drift. The parser retries invalid GPT outputs with validation feedback.
- `gpt-5-mini` is the best default here because it supports web search and is positioned by OpenAI as the lower-cost option compared with larger GPT-5-class models.
- GPT bracket generation is parallelized, and by default each GPT bracket now does its own research call unless you use `--skip-research`.
- The heuristic simulator is parameter-driven: there are no named heuristic strategies anymore, only the threshold settings and RNG seed.
- If you want a lot of brackets and do not need them immediately, adapting the generation phase to the Batch API is the next cost optimization.

## Visualizer site

The repo also includes a local site for browsing brackets in [`/Users/jxshix/Documents/marchmadness/final_output`](/Users/jxshix/Documents/marchmadness/final_output), entering actual game results, and ranking brackets on a live leaderboard.

Build the combined site data:

```bash
node /Users/jxshix/Documents/marchmadness/build_site_data.mjs
```

Install the Node dependencies:

```bash
npm install
```

Start the app locally with Postgres-backed persistence:

```bash
export DATABASE_URL=postgresql://...
npm start
```

Then open [http://localhost:3000/site/](http://localhost:3000/site/).

Notes:

- Brackets are grouped by source filename.
- The selected bracket now renders as a bracket board at the top of the page.
- Ground-truth results are entered manually and stored in Postgres when the API is available.
- If the API is unavailable, the frontend falls back to browser-local storage.
- You can export and import the ground-truth JSON to move it between browsers or machines.
- Leaderboard scoring uses round weights of 1, 2, 4, 8, 16, and 32 points.

## Railway deployment

Railway setup should use:

- Build command: `npm install && npm run build:data`
- Start command: `npm start`
- Environment variable: `DATABASE_URL` from Railway Postgres
- Config file: [`/Users/jxshix/Documents/marchmadness/railway.json`](/Users/jxshix/Documents/marchmadness/railway.json) is included

Suggested deploy flow:

1. Push this repo to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Add a PostgreSQL service.
4. In the app service, attach the `DATABASE_URL` reference from the PostgreSQL service.
5. Deploy. Railway will use the included `railway.json`.
6. Open `/site/` on the deployed app URL.

Before redeploying after generating new brackets locally, rebuild the bundled data:

```bash
npm run build:data
```

The app serves:

- `/site/` for the frontend
- `/site_data/brackets.json` for the generated bracket payload
- `/api/ground-truth/:fieldKey` for the stored tournament results
