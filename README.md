# kubeagent

An autonomous Kubernetes troubleshooting agent built on
[LlamaIndex](https://docs.llamaindex.ai/) `FunctionAgent`/`AgentWorkflow`
(not LangGraph). It drives the Kubernetes API through a read-only diagnostic
ladder — pods, then describe, then logs, then events, then rollout history —
via the official `kubernetes` Python client (no `kubectl` binary), and
reports a root cause. Two gated remediation tools (restart / rollback a
Deployment) exist behind a human-approval step, so the agent can act, but
never without an operator saying yes.

There are two ways to run it:

- **Service** (`app/`) — a FastAPI microservice exposing `/diagnose` as a
  background job with a polling + approval API. Meant to run in-cluster.
- **Standalone example** (`examples/k8s_rabbit_hole.py`) — a single script
  with no service, no approval gate, and no write tools at all; it reuses the
  same read-only `app.kube.api` layer. Point it at a namespace and it
  investigates unattended.

## Safety model

All cluster access goes through the official `kubernetes` Python client
talking to the apiserver over HTTPS — **no `kubectl` (or any other) binary is
ever invoked**. Because every call is a typed API request (list pods, read
logs, read/patch a deployment), there is no shell, no argv to escape, and no
way to reach `secrets`, `exec`, or `portforward`: those endpoints are simply
never called and are not granted by RBAC.

- **Read path** (`app/kube/api.py` + `app/kube/read_tools.py`): the only
  policy left to enforce in code is namespace scoping
  (`app/kube/safety.py`), which fails closed — an empty
  `KUBE_ALLOWED_NAMESPACES` denies every namespace. In-cluster config loads
  from the mounted ServiceAccount token, falling back to the local kubeconfig
  for development.
- **Write path** (`app/kube/mutate.py`) is not a generic passthrough. Exactly
  two operations exist — a rolling *restart* (a strategic-merge patch stamping
  the `kubectl.kubernetes.io/restartedAt` annotation on the pod template) and
  an *undo* (re-applying the previous revision's ReplicaSet pod template) —
  and this function is only ever reached from `app/agents/write_tools.py`
  *after* an operator approval resolves. There is no code path that lets the
  LLM invoke it directly.
- **Approval gate** (`app/agents/hitl.py`): LlamaIndex has no
  `HumanInTheLoopMiddleware`, so a small `ApprovalStore` fills the gap.
  A write tool calls `request()`, which hands back an `asyncio.Future`; the
  tool `await`s it (bounded by `APPROVAL_TIMEOUT_SECONDS`, defaulting to a
  rejection on timeout). Because each investigation runs as a background
  `asyncio.Task`, the agent loop genuinely suspends mid-tool-call and
  resumes once `POST /diagnose/{id}/decisions` resolves it — no workflow
  serialization needed.
- **RBAC** (`k8s/base/`): a broad *read* `ClusterRole` (`get,list,watch` on
  `pods, pods/log, events, deployments, replicasets, statefulsets`; no
  secrets, no `pods/exec`, no `pods/portforward`) and a narrow *write*
  `Role` (`get,patch` on `deployments` only), kept as separate,
  independently revocable resources. Both are bound to the same
  `kubeagent-readonly` ServiceAccount, because the Deployment runs as a
  single pod identity — there's no clean way for one running pod to assume
  two distinct ServiceAccounts without extra `TokenRequest` machinery, and
  the write tools execute in-process in the same pod as the read tools. The
  narrow write grant can still be revoked independently by deleting
  `rolebinding-remediation.yaml` without touching the read-only binding.

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # then fill in LITELLM_* and KUBE_ALLOWED_NAMESPACES
```

Run the service:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Run the checks:

```bash
uv run pytest
uv run ruff format --check . && uv run ruff check .
uv run mypy app examples
```

### Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `LITELLM_API_BASE` / `LITELLM_API_KEY` / `LITELLM_API_MODEL` | LiteLLM-routed model endpoint, used by both the service (`app/core/llm.py`) and the standalone script. |
| `LITELLM_MAX_TOKENS` | Max output tokens (default `4096`). |
| `KUBE_ALLOWED_NAMESPACES` | Comma-separated namespace allowlist. **Empty denies everything.** |
| `KUBE_MAX_HOPS` | Hop budget before an investigation is forced to converge (default `8`). |
| `APPROVAL_TIMEOUT_SECONDS` | How long a pending restart/rollback approval waits before it's treated as rejected (default `600`). |
| `HEALTH_PORT` | Port for the dedicated `/healthz`/`/readyz`/`/metrics` server (default `8001`). |
| `HEARTBEAT_INTERVAL_SECONDS` | How often the main event loop stamps a heartbeat (default `2`). |
| `HEALTH_STALE_SECONDS` | How long the heartbeat can go unrefreshed before `/healthz`/`/readyz` report the loop as stalled (default `10`). |
| `DEPENDENCY_CHECK_INTERVAL_SECONDS` | How often to re-check Kubernetes-API/LiteLLM reachability for `/readyz` and `/metrics` (default `15`). |

## API

Start an investigation (`namespace` must be in `KUBE_ALLOWED_NAMESPACES`):

```bash
curl -X POST localhost:8000/diagnose \
  -H 'content-type: application/json' \
  -d '{"namespace": "staging", "focus": "payments deployment"}'
# {"id": "...", "status": "running"}
```

Poll it:

```bash
curl localhost:8000/diagnose/<id>
```

```jsonc
{
  "id": "...",
  "namespace": "staging",
  "status": "awaiting_approval",
  "trail": ["get_pods", "describe_pod:web-1", "restart_deployment:web"],
  "pending_approval": {
    "tool_name": "restart_deployment",
    "arguments": {"deployment": "web", "namespace": "staging"},
    "requested_at": "..."
  },
  "result": null,
  "error": null
}
```

Approve or reject the pending action:

```bash
curl -X POST localhost:8000/diagnose/<id>/decisions \
  -H 'content-type: application/json' \
  -d '{"decision": "approve", "reason": "restart looks safe"}'
```

Poll `/diagnose/<id>` again for `status: completed` and a `result` in the
`SYMPTOM / EVIDENCE / ROOT CAUSE / RECOMMENDED ACTION` format.

List all investigations (newest first) if you've lost an id:

```bash
curl localhost:8000/diagnose
# [{"id": "...", "namespace": "staging", "status": "completed", "created_at": "..."}, ...]
```

Health checks and metrics live at `/healthz`, `/readyz` and `/metrics` on
a separate port (`HEALTH_PORT`, default `8001`) — see
[Health checks and metrics](#health-checks-and-metrics) below.

## Health checks and metrics

`/healthz`, `/readyz` and `/metrics` are served by a small stdlib
`http.server` (`app/health_server.py`) running on its own thread and
socket, on `HEALTH_PORT` (default `8001`) — not as FastAPI routes on the
main app port. The main app runs on a single asyncio event loop; a
long-running LLM call or (hypothetically) a blocking Kubernetes API call
there would stall every coroutine on that loop, including a health route
defined on the same app. Answering probes from a separate thread/socket
means the HTTP response itself never blocks behind that.

That isolation alone isn't enough: a handler that always returns `200`
would keep reporting healthy even if the main loop were genuinely stuck
(deadlocked, or blocked by a bug), which is exactly the case a probe is
supposed to catch. So the main app runs a periodic task
(`HEARTBEAT_INTERVAL_SECONDS`, default every `2`s) that stamps a shared
timestamp, and the health server checks it: if the last heartbeat is
older than `HEALTH_STALE_SECONDS` (default `10`), `/healthz`/`/readyz`
switch to `503`. A single legitimately long request doesn't trip this —
`await` still yields control between steps, so the heartbeat keeps
beating — but a truly stalled loop does, so Kubernetes can restart a pod
that's actually stuck rather than one that's merely busy investigating.

`/healthz` and `/readyz` answer different questions, and are wired to
different probes on purpose:

- **`/healthz` (liveness)** only reflects the heartbeat above. A stuck
  process should be restarted; nothing else should ever flip this,
  because restarting a pod can't fix a problem that lives outside it.
- **`/readyz` (readiness)** additionally reports the cached reachability
  of this service's two hard dependencies — the Kubernetes API (via the
  client's `/version` probe, `app/core/dependency_checks.py`) and the LiteLLM
  endpoint —
  checked on a periodic background task (`DEPENDENCY_CHECK_INTERVAL_SECONDS`,
  default `15`s) and served from cache, never a live call during the
  probe itself. If either is unreachable the agent can't do its job
  right now, so `/readyz` returns `503` and Kubernetes pulls the pod out
  of Service routing — without killing it, since restarting fixes
  nothing when the outage is external.

```bash
curl localhost:8001/healthz
# {"status": "ok", "pod": "kubeagent-7f8c9d-abcde"}

curl localhost:8001/readyz
```

```jsonc
{
  "status": "ready",
  "pod": "kubeagent-7f8c9d-abcde",
  "checks": {
    "loop": {"ok": true, "status": 200, "message": "event loop heartbeat fresh"},
    "kube_api": {"ok": true, "status": 200, "message": "Kubernetes API reachable"},
    "llm": {"ok": true, "status": 200, "message": "LiteLLM endpoint reachable"}
  }
}
```

`/metrics` exposes the same heartbeat-age and per-dependency signals plus
investigation counts by status, in Prometheus text exposition format —
no `prometheus_client` dependency, hand-rolled to match this module's
stdlib-only approach:

```bash
curl localhost:8001/metrics
```

```
kubeagent_up 1
kubeagent_event_loop_heartbeat_age_seconds 0.42
kubeagent_dependency_up{dependency="kube_api"} 1
kubeagent_dependency_up{dependency="llm"} 1
kubeagent_investigations_total{status="running"} 1
kubeagent_investigations_total{status="awaiting_approval"} 0
kubeagent_investigations_total{status="completed"} 3
kubeagent_investigations_total{status="failed"} 0
```

Unlike `/healthz`/`/readyz`, `/metrics` always returns `200` with the true
current numbers, even while stale — it reports facts for
Prometheus/alerting to act on, rather than encoding a restart verdict.

## Standalone example

Fully autonomous and read-only — it builds its own LLM client and reuses the
service's read-only `app.kube.api` layer (the same direct-to-apiserver
client, no `kubectl` binary), and never mutates the cluster.

```bash
python -m examples.k8s_rabbit_hole staging
python -m examples.k8s_rabbit_hole staging "focus on payments"
python -m examples.k8s_rabbit_hole staging --max-hops 12
```

It streams each tool call to the console and stops when it emits a
`DIAGNOSIS_COMPLETE` report, or when its hop budget runs out.

## Deploying to Kubernetes

Manifests are under `k8s/base/` (a `kustomization.yaml` ties them
together):

```bash
kubectl apply -k k8s/base
```

The Deployment's `envFrom` expects two objects that are **not** created by
these manifests — create them yourself, scoped to your own secrets
management:

```bash
kubectl create secret generic kubeagent-litellm -n kubeagent \
  --from-literal=LITELLM_API_BASE=https://your-litellm-host \
  --from-literal=LITELLM_API_KEY=your-litellm-api-key

kubectl create configmap kubeagent-config -n kubeagent \
  --from-literal=LITELLM_API_MODEL=openai/gpt-4.1-20250414-global \
  --from-literal=KUBE_ALLOWED_NAMESPACES=staging \
  --from-literal=KUBE_MAX_HOPS=8 \
  --from-literal=APPROVAL_TIMEOUT_SECONDS=600
```

Build and push the image referenced by `deployment.yaml`
(`kubeagent:latest`) with the included multi-stage `Dockerfile`.

The `kubeagent` Service exposes both the `http` port (`8000`, the API) and
the `health` port (`8001`, `/healthz`/`/readyz`/`/metrics`) — kubelet
probes hit the pod IP directly regardless, but the Service's `health`
port lets an in-cluster Prometheus (or anything else) reach `/metrics`
without going through the pod IP. The pod template also carries
`prometheus.io/scrape`/`port`/`path` annotations for annotation-based
Prometheus discovery; drop them (and the Service's `health` port) if your
cluster uses a different discovery mechanism (e.g. a `ServiceMonitor`).

Confirm the RBAC boundary:

```bash
kubectl auth can-i --as=system:serviceaccount:kubeagent:kubeagent-readonly delete pods
# no
```

### Distributed tracing (OpenTelemetry)

Tracing is **opt-in and disabled by default**. With no
`OTEL_EXPORTER_OTLP_ENDPOINT` set, `app/core/telemetry.py` is a no-op.
Point it at an OTLP/HTTP collector to trace each investigation end to end —
the inbound request, the background agent workflow (one `investigation`
span carrying `kube.namespace`, `investigation.hops`, and status), and the
outbound LLM calls to LiteLLM (auto-instrumented over httpx). W3C trace
context is propagated on the LiteLLM hop, so if the upstream model service
exports to the same collector the spans join one trace. See
`k8s/examples/llama-stack-tracing.yaml` for the Llama Stack / LiteLLM side
(also disabled by default). Following
[Red Hat's distributed-tracing-for-agentic-workflows guide](https://developers.redhat.com/articles/2026/04/06/distributed-tracing-agentic-workflows-opentelemetry).

## Project layout

```
app/
├── main.py                 # FastAPI app: diagnose, wires up the health server
├── schemas.py               # Pydantic request/response models
├── core/                    # settings + LLM client
├── routers/                 # diagnose
├── kube/                    # envelope, safety (read), mutate (write)
├── agents/                  # prompts, steer (hop budget), hitl (approval
│                             gate), write_tools, troubleshooter (agent loop)
└── persistence/              # in-memory investigation store
examples/k8s_rabbit_hole.py  # standalone autonomous read-only script
k8s/base/                    # namespace, RBAC, Deployment, Service
```
