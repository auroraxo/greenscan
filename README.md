# greenscan

Free, read-only **n8n** reliability audit. One file. No dependencies. No account.

Point it at your n8n instance with an API key. It reads your workflows and
the last few days of executions, then prints a one-page report covering the
six failure classes the n8n community has named in 2025–2026:

```
A. hard_error         — n8n's Error Workflow catches these; flag only if many.
B. missed_run         — active scheduled workflow hasn't fired in the window.
C. early_end          — execution was green but stopped before the last node.
D. empty_output       — successful run produced zero items.
E. coaf_risk          — node has continueRegularOutput + alwaysOutputData;
                        downstream 5xx becomes a green execution that still
                        writes downstream state.
F. zombie             — active scheduled workflow with no recent executions.
```

It is not a continuous monitor. It does not verify the business outcome.
It does not write to your instance. It does not call home. Re-run as often
as you want.

## Install

No install. Two options:

```bash
# Option 1: one-liner via curl (pinned, requires Python ≥ 3.8)
curl -sSL https://raw.githubusercontent.com/auroraxo/greenscan/v0.1.0/greenscan.py \
  -o greenscan.py && python3 greenscan.py --base-url https://n8n.example.com

# Option 2: clone
git clone https://github.com/auroraxo/greenscan
cd greenscan
python3 greenscan.py --base-url https://n8n.example.com
```

Zero non-stdlib dependencies. The script uses only `urllib`, `json`, `argparse`,
`datetime`, `collections`, and `re`.

## Use

```bash
export N8N_API_KEY="n8n_api_xxxxxxxxxxxxxxxxxxxxx"
python3 greenscan.py --base-url https://n8n.example.com

# n8n Cloud
python3 greenscan.py --base-url https://acme.app.n8n.cloud

# 14-day window, JSON output
python3 greenscan.py --base-url https://n8n.example.com --days 14 --json > report.json

# No instance? Try the bundled demo data
python3 greenscan.py --dry-run
```

You can create the API key at **Settings → n8n API** in your n8n UI. Use
the shortest expiry you can. greenscan reads; it does not write, so the
key only needs read access (`workflow:read`, `execution:read`).

## Exit codes

| code | meaning                                |
| ---- | -------------------------------------- |
| 0    | report generated, no findings          |
| 1    | report generated, one or more findings |
| 2    | bad arguments or cannot reach instance |

## Why it exists

I read this thread and the linked cost thread on community.n8n.io:

- [Looking for 3 n8n users with real workflow reliability issues](https://community.n8n.io/t/310860)
- [When a silent failure hit you, what did it actually cost?](https://community.n8n.io/t/316526)

The cost numbers in there: **$2,500–$8,000 per incident, 48 h to 3 weeks to
detect, 6–15 billable hours to find**. The failure the lead describes:

> The execution list is a wall of green.

Three paid vendors already serve this market continuously: Watchflow,
Midwatch, OutcomeGuard. They all do the right thing — they read execution
history, they baseline each workflow, they alert. They all charge $19–$99
per month.

What none of them ship is the **before** step: a free, no-signup, one-shot
audit you can run in 30 seconds to see whether you have the problem at
all. If the report comes back empty, you didn't need them. If it comes
back with `coaf_risk` or `missed_run` for three of your production
workflows, you know exactly what you would have paid them for.

greenscan is the before step. It is not a replacement for a continuous
monitor. It is the thing you run before you decide to buy one.

## What greenscan will not do

- It will not watch your instance in real time.
- It will not page you.
- It will not verify a WhatsApp message reached the recipient, that a
  Stripe charge actually settled, or that a row was actually written to
  the downstream database. Those are outcome checks; they require either
  delivery callbacks from the upstream service or a read against the
  destination. greenscan reads n8n only.
- It will not install a node into your workflow, change settings, or
  modify any state.

If you need those, the next step is to run a continuous monitor or to
read community.n8n.io/t/316526 and pay an agency for a one-week
reconciliation pass.

## Privacy

- No telemetry.
- No outbound calls except to the `--base-url` you provide, with the API
  key you provide.
- The API key is read once per run from the environment or the CLI and
  never written to disk by this script.
- The `--json` output is just the report. It contains no credentials,
  no execution data fields, only metadata (status, count, last node).

## Tested against

- n8n 1.x self-hosted (1.74+ at time of writing).
- n8n Cloud (Starter, Pro, Enterprise).

If a future n8n version changes the execution response shape, the script
will degrade gracefully: any check that cannot compute from the new
shape will simply not report on it, rather than crashing.

## Author

Aurora — [codebyaurora.com](https://codebyaurora.com). MIT. Source on
GitHub: [auroraxo/greenscan](https://github.com/auroraxo/greenscan).
