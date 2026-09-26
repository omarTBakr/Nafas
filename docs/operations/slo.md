# Service level objectives

What "working" means for Nafas, in numbers the dashboards and alerts check
(`deploy/prometheus/alerts.yml`) and the load test enforces
(`scripts/load_test.py`, which exits non-zero on a miss and so can gate a
promotion). The targets are for a first clinic's traffic and should be
revisited with a quarter of real data.

## Objectives

| What | Objective | Measured by | Alert |
|---|---|---|---|
| Every service answers | 99.5% of scrapes over 30 days | `up{job="nafas"}` | `ServiceDown` after 2 min |
| Requests succeed | 99.5% not 5xx, per service, over 30 days | `nafas_http_requests_total` | `HighErrorRate` above 2% for 10 min |
| Pages and reads are quick | 95% under 1 s at the gateway (outside chat) | `nafas_http_request_seconds` | `GatewaySlow` for 15 min |
| Sign-up and login | 95% under 2 s (password hashing is slow on purpose) | load test | none; the load test gates |
| A chat reply arrives | 95% within 12 s (booking tools and safety gates run before the answer) | `/api/chat` routes | `ChatSlow` for 15 min |
| A visit note is drafted | 95% within 5 min of the doctor stopping the recording | Temporal `ConsultationWorkflow` durations | `WorkflowFailures` |
| A document is searchable | 95% within 2 min of upload | `DocumentIngestionWorkflow` durations | `WorkflowFailures` |
| An escalation reaches the doctor | every one, at once (it is a row the inbox reads) | `nafas_escalations_total` | `EmergencySpike` for clusters |

The error budget is the gap to 100%: 0.5% of requests, about 3.6 hours of a
fully failing service a month. When a month's budget is spent, changes stop
except fixes to reliability until it recovers.

## What is not an objective

- **The model's own latency.** Claude's p95 is on the dashboard
  (`nafas_llm_call_seconds`) and inside the chat objective; it is not ours to
  promise separately.
- **Safety.** Emergencies are caught by plain code before any model, every
  gate fails closed, and the eval set (`services/conversation/evals`) has its
  own thresholds, emergencies at 100%. A safety miss is an incident, never a
  budget to spend.

## Behavioural signals

These have no SLO; a change in them means the model or a prompt drifted and
someone should look (`docs/operations/runbook.md#behaviour-drift`):

- the output guard blocking more answers (`GuardBlockingMore`, above 10%)
- the scope gate failing to decide (`GatesFailingClosed`, above 5%)
- doctors rewriting nearly every visit note (`VisitNotesMostlyRewritten`, above 90% in a week)
- held slots lapsing unconfirmed (`HoldsLapsing`, above half in a day)
- thumbs-down on replies (`nafas_reply_feedback_total`), read with the feedback export
