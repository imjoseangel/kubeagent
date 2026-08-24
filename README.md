# kubeagent

An autonomous Kubernetes troubleshooting agent built on
[LlamaIndex](https://docs.llamaindex.ai/) `FunctionAgent`/`AgentWorkflow`
(not LangGraph). It drives `kubectl` through a read-only diagnostic ladder
— pods, then describe, then logs, then events, then rollout history — and
reports a root cause. Two gated remediation tools (restart / rollback a
Deployment) exist behind a human-approval step, so the agent can act, but
never without an operator saying yes.

There are two ways to run it:

- **Service** (`app/`) — a FastAPI microservice exposing `/diagnose` as a
  background job with a polling + approval API. Meant to run in-cluster.
- **Standalone example** (`examples/k8s_rabbit_hole.py`) — a single
  self-contained script with no service, no approval gate, and no write
  tools at all. Point it at a namespace and it investigates unattended.

## Safety model

- **Read path** (`app/kube/safety.py`, mirrored in the standalone example):
  a hard verb allowlist (`get, describe, logs, top, events`), a hard
  forbidden set (`delete, exec, edit, apply, patch, replace, cp, attach,
  port-forward`), any argument containing `secret` refused outright, and a
  namespace allowlist that fails closed — an empty `KUBE_ALLOWED_NAMESPACES`
  denies every namespace. Every call runs via `subprocess.run(["kubectl",
  *args], ...)` with a list argv — never a shell string, so there is no
  injection surface.
- **Write path** (`app/kube/mutate.py`) is not a generic kubectl
  passthrough. Exactly two command shapes exist —
  `rollout restart deployment/<name> -n <ns>` and
  `rollout undo deployment/<name> -n <ns>` — and this function is only ever
  reached from `app/agents/write_tools.py` *after* an operator approval
  resolves. There is no code path that lets the LLM invoke it directly.
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
long-running LLM call or (hypothetically) a blocking `kubectl` call there
would stall every coroutine on that loop, including a health route
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

```bash
curl localhost:8001/healthz
curl localhost:8001/readyz
```

`/metrics` exposes the same heartbeat-age signal plus investigation
counts by status, in Prometheus text exposition format — no
`prometheus_client` dependency, hand-rolled to match this module's
stdlib-only approach:

```bash
curl localhost:8001/metrics
```

```
kubeagent_up 1
kubeagent_event_loop_heartbeat_age_seconds 0.42
kubeagent_investigations_total{status="running"} 1
kubeagent_investigations_total{status="awaiting_approval"} 0
kubeagent_investigations_total{status="completed"} 3
kubeagent_investigations_total{status="failed"} 0
```

Unlike `/healthz`/`/readyz`, `/metrics` always returns `200` with the true
current numbers, even while stale — it reports facts for
Prometheus/alerting to act on, rather than encoding a restart verdict.

## Standalone example

Fully autonomous, read-only, and self-contained — it imports nothing from
`app`, builds its own LLM client and its own copy of the kubectl safety
wrapper, and never mutates the cluster.

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

Confirm the RBAC boundary:

```bash
kubectl auth can-i --as=system:serviceaccount:kubeagent:kubeagent-readonly delete pods
# no
```

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
