# Demo worker recovery

Run one MS process. Local request work and backend polling run in separate tasks: a busy local queue cannot
prevent polling. Each poll pass visits at most five submitted requests, rotates through them, and limits each
backend status call to 15 seconds. Evidence fetching retains its existing per-listing limits.

MS persists the current processing stage. After a restart, unfinished processing becomes `interrupted` and
waits for operator review. From the repository root, use the existing MS Python environment:

```powershell
$env:PYTHONPATH = 'main-service'
python -m main_service.recovery --database main-service/var/requests.sqlite3 list
python -m main_service.recovery --database main-service/var/requests.sqlite3 retry <order-id>
```

Use the actual configured `MS_DATABASE` path. The CLI requires an existing database and prints IDs, stages,
and retry eligibility, not account profiles or credentials. Retry is transactional and only accepts interrupted
requests. It queues work for the running service, or for its next startup; it does not itself call providers.

| Interrupted stage | Retry behavior |
|---|---|
| `preparing` | Reparse and compile the original authorized request; an LLM call may be repeated. |
| `agent_verification` | Fetch/check the saved candidate batch against the same requirements; never run managed search. |
| `managed_verification` | Check the already saved backend response; never resubmit its search request. |
| `submitting_backend` or unknown older stage | Refuse retry: the backend may already have received the request. Reconcile it externally first. |

A backend error during submission is also recorded as `interrupted` because delivery may be uncertain.
There is intentionally no force-retry action. These recovery actions neither approve nor execute purchases.
Candidate evidence is fetched again on retry and may have changed; batch IDs and requirements remain stable.
The latest retry count, time and stage are retained with the result. A restarted submitted backend job resumes
read-only polling; a failed business/policy decision is not automatically retried.
