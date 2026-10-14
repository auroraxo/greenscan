# Distribution drafts (ready to paste)

Posting to community.n8n.io and Hacker News needs a logged-in account; no
credentials are stored on this machine. These drafts are the exact texts —
paste and send when a session exists.

Target threads:

1. Reply to the lead pilot thread — https://community.n8n.io/t/310860
2. Reply to the cost thread — https://community.n8n.io/t/316526
3. Show HN submission — https://news.ycombinator.com/submit

---

## 1. Reply to t/310860 (Hilario's pilot thread)

Subject: Re: Looking for 3 n8n users with real workflow reliability issues

I built a free, read-only audit for exactly this class of failure — greenscan
(https://github.com/auroraxo/greenscan). One Python file, stdlib only, no
account. It reads workflows + execution history through the public API and
flags the six failure modes that keep recurring in threads like this:

- A hard_error — many recent errored executions
- B missed_run — active schedule, last run older than your window
- C early_end — green execution that stopped before the last node
- D empty_output — successes producing zero items (n>=5, >=50%, so small
  samples don't cry wolf)
- E coaf_risk — onError: continueRegularOutput + alwaysOutputData: true,
  which is precisely the two-property mistake behind the 13 burned touches
  in Cristian's incident
- F zombie — active schedule with no executions at all

    curl -sSL https://raw.githubusercontent.com/auroraxo/greenscan/v0.1.0/greenscan.py -o greenscan.py
    export N8N_API_KEY=n8n_api_xxx
    python3 greenscan.py --base-url https://your-instance

Honest scope note, since Cristian asked the decisive question in this
thread: greenscan is a report, not a control. It reads history after the
fact; it does not sit in the path or hold a run pending confirmation.
If what you want is the gate, that is the next thing I am building, and
Cristian's framing — "nobody was told in time to do anything about it" —
is the requirement I am designing against.

Happy to run it against a sanitized export for any of the pilot cases.

---

## 2. Reply to t/316526 (cost thread)

Subject: Re: When a silent failure hit you, what did it actually cost?

Numbers in this thread convinced me the diagnosis step is the wedge, so I
built it and gave it away: greenscan
(https://github.com/auroraxo/greenscan).

It does not alert, monitor, or verify delivery — it answers "do I even have
this problem" in one run, read-only, against your own instance, without an
account. For jeevethaa's pricing point: it is deliberately the step before
the recurring tools, so you only pay a monitor after the free audit shows
findings worth monitoring.

Check C (early end) and D (empty output) are the two that map to "green
run, nothing happened." Exit code 1 means findings; --json if you want to
diff runs in CI.

---

## 3. Show HN

Title: greenscan — free read-only audit for n8n silent failures

URL: https://github.com/auroraxo/greenscan

Comment:

n8n reports what the engine did, not what your business did. A run finishes
green while the message never sent or the row never wrote, and operators
find out days later from a client. The n8n community has priced this
($2.5k-8k per incident, 48h-3 weeks to notice — community.n8n.io/t/316526).

Existing answers are recurring monitors at $19-99/mo (Watchflow, Midwatch,
OutcomeGuard). greenscan is the step before that: one Python file, stdlib
only, no account, no telemetry. It reads your instance through the public
API and flags six failure classes, including the specific trap where
onError: continueRegularOutput + alwaysOutputData: true turns a downstream
5xx into a green execution that still writes state.

    curl -sSL https://raw.githubusercontent.com/auroraxo/greenscan/v0.1.0/greenscan.py -o greenscan.py
    export N8N_API_KEY=n8n_api_xxx   # Settings -> n8n API
    python3 greenscan.py --base-url https://n8n.example.com

Exit 0 clean, 1 findings, 2 unreachable. --dry-run for demo data.

Honest about what it is not: it is a report, not a control. It cannot hold
a run until a human confirms, and it cannot verify a downstream delivery —
those need callbacks or a read against the destination. This reads n8n
only. Landing page: https://codebyaurora.com/greenscan/
