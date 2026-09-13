# Local web API

The web application is a dependency-free HTTP/1.1 interface over the same decision
engine and append-only store as the CLI. It listens on `127.0.0.1:8787` by default.
V0 refuses non-loopback binding because it has no user authentication or TLS.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Verify the store and report its event count |
| `GET` | `/api/v1/overview` | List decisions with status and obligation counts |
| `GET` | `/api/v1/decisions/{id}` | Return the definition, assessment, and experiments |
| `POST` | `/api/v1/decisions` | Validate and create `decisions/{id}.json` without overwriting |
| `GET` | `/api/v1/events?decision={id}` | Return all events or one decision's linked history |
| `GET` | `/api/v1/artifacts/{sha256}` | Download and integrity-check a retained SQLite database |
| `POST` | `/api/v1/runs` | Run one, the next, or every registered experiment |
| `POST` | `/api/v1/annotations` | Append an unexpected effect, hypothesis, or resolution |

Mutation bodies are JSON and limited to 1 MB. `Origin`, when present, must match
the request host. Decisions are found only as direct JSON children of `decisions/`
and `examples/`; API callers identify them by validated decision ID. Artifact names
must be lowercase SHA-256 digests. Static route fallback serves only the three
packaged application assets.

`POST /api/v1/runs` executes synchronously in this first full-stack version. Its
body is `{"decision":"enable-replay","experiment":"crash-gap"}` or uses
`"all":true`. A successful HTTP response means the plan completed and its results
were retained. The returned assessment decides whether evidence supports the
claim. Uncommitted or modified definitions and adapter sources are rejected before
the intervention.

`POST /api/v1/annotations` accepts:

```json
{"kind":"unexpected","target":"PLAN_EVENT_ID","note":"Observed consequence"}
```

`kind` can also be `hypothesis` or `resolution`; a resolution includes a registered
`choice`. An annotation appends history and never alters prior evidence.

The server is suitable for one operator on a trusted workstation. It has no claim
leasing, job queue, cancellation, authentication, or concurrent source-editing
protocol. Those belong in a later multi-user service design rather than being
implied by a development server.
