# Nafas

An AI assistant for patients and doctors. Patients book and ask questions over
Telegram or email, by text or voice. Doctors get a dashboard, a less
restricted assistant, and session summaries. The plan is in
[docs/PLAN.md](docs/PLAN.md) and the order of work in
[docs/CHECKLIST.md](docs/CHECKLIST.md).

Every feature is its own service. They all live in this one repository as a uv
workspace and coordinate through Temporal.

## Contents

- [Getting started](#getting-started)
  - [Requirements](#requirements)
  - [Setup](#setup)
- [Running it](#running-it)
  - [The whole stack](#the-whole-stack)
  - [One service on the host](#one-service-on-the-host)
- [How the code is arranged](#how-the-code-is-arranged)
  - [Services and the core library](#services-and-the-core-library)
  - [Inside a service](#inside-a-service)
  - [Adding a service](#adding-a-service)
- [Conventions](#conventions)
  - [Formatting and linting](#formatting-and-linting)
  - [Pre-commit hooks](#pre-commit-hooks)
  - [Tests](#tests)
- [Things that will bite you](#things-that-will-bite-you)
- [License](#license)

## Getting started

### Requirements

- Python 3.12 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- Node 22, for the web app in `web/` (`npm ci` there once).
- Docker with Compose, on the **native engine** (not Docker Desktop), plus the
  NVIDIA container toolkit for the GPU services. The `Makefile` pins the
  `default` context, and `make gpu-check` proves a container can see the GPU.
  The suite still runs without Docker: database and storage tests skip.

### Setup

```bash
uv sync                       # every workspace package, editable
uv run pre-commit install     # once, so the hooks run on every commit
cp .env.example .env          # optional: every setting already has a default

make up                       # Postgres :5433, Temporal :7234 (UI :8234), S3 :8333, services
make migrate                  # apply database migrations
make seed                     # the specializations
make storage                  # create the bucket
```

A doctor to log in as, with hours to book:

```bash
uv run python -m nafas_identity.cli create-doctor --email dr@example.com \
  --name-en "Dr Example" --name-ar "د. مثال" --specialization cardiology
uv run python -m nafas_scheduling.cli set-hours --doctor-id <printed id> \
  --hours wed=17:00-21:00 --hours sat=10:00-14:00/in_person
```

Check it works:

```bash
make test
```

## Running it

### The whole stack

`make up` builds and starts the infrastructure and every service that exists
so far. On a machine without an NVIDIA GPU, use `make up-cpu`, where GPU
services fall back to the CPU. `make logs`, `make ps` and `make down` do what
they say.

| Service | Where | What |
| --- | --- | --- |
| web | :8088 | **the app**: patient portal and doctor portal (nginx; `make web-dev` for hot reload on :5173) |
| gateway | :8000 | the web app's API: auth and sign-up, the doctor directory, booking, the doctor's schedule |
| identity | :8010 | internal API (behind `X-Internal-Token`): accounts, sign-up, the doctor directory, care links |
| scheduling | :8030 | internal API (behind `X-Internal-Token`): slots, exact-minute checks, holds, confirm, cancel |
| dialect-router | :8410 | Arabic dialect identification on the GPU; `POST /v1/classify`, `/health`, `/metrics` |

### One service on the host

While working on a service, run it on the host against the containers:

```bash
uv run python -m nafas_gateway.main
```

## How the code is arranged

### Services and the core library

```
packages/core/         nafas_core: settings, logging, LangSmith tracing, db, Temporal,
                       provider interfaces, shared enums and exceptions
services/gateway/      nafas_gateway: the dashboard's HTTP edge (login, sessions)
services/identity/     nafas_identity: accounts, doctors, patients, consents
services/scheduling/   nafas_scheduling: hours and appointments, to the minute
services/conversation/ nafas_conversation: the patient's assistant chat (a Temporal worker)
web/                   the React app: patient and doctor portals, Arabic (RTL) and English
services/dialect_router/   GPU inference service, outside the workspace
alembic/               one migration history for every service's schema
docker/                the shared Dockerfile for workspace services
```

The service map and its rules are in [docs/PLAN.md §4](docs/PLAN.md). In short:
- A service owns one Postgres schema and one Temporal task queue (`nafas_core.temporal.TaskQueue`).
- It reaches anything else only by calling the service that owns it.
- Foreign keys into another service's schema live in the migrations, never on ORM models, so a service runs on its own code alone.

GPU services such as `dialect_router` sit outside the workspace, with their own
lockfile (CUDA-pinned PyTorch) and their own Dockerfile.

### Inside a service

The shape is deliberate: logic in the middle, adapters at the edges.

| Module | Holds | Rule |
| --- | --- | --- |
| `routes/` | FastAPI routers | Validate, start or query a workflow, map errors. No logic. |
| `activities/` | Temporal activities | One side effect each, a thin wrapper over `logic`. |
| `workflows/` | Temporal workflows | Decide order. Never do I/O. |
| `schemas/` | Dataclasses crossing a Temporal boundary | Plain dataclasses; they get encoded to JSON. |
| `logic/` | The actual work | No Temporal, no FastAPI. Testable by calling a function. |
| `prompts/` | Prompts as data | A reviewable diff in one place, versioned. |
| `models.py` | ORM models | On `nafas_core.db.Base`, in the service's own schema. |
| `worker.py` | Entrypoint | `run_worker(TaskQueue.X, WORKFLOWS, ACTIVITIES)`. |

The reason for the split is testing: `logic` has no framework imports, so most
of the suite never starts a server or a task queue.

### Adding a service

1. `services/<name>/pyproject.toml` depends on `nafas-core` with
   `{ workspace = true }`, and the root `pyproject.toml` gains it as a
   dependency and a source.
2. Its package is `services/<name>/nafas_<name>/`, laid out as above, with tests
   in `services/<name>/tests/`.
3. If it runs a worker, add its queue to `TaskQueue`. If it has tables, add its
   models module to `MODEL_MODULES` in `alembic/env.py`.
4. Add it to `docker-compose.yml` with `docker/service.Dockerfile` and its
   `PACKAGE` and `MODULE` build arguments.

## Conventions

### Formatting and linting

black and ruff, both at line length 130, configured in `pyproject.toml`. ruff
runs pycodestyle, pyflakes, isort, pyupgrade and bugbear.

```bash
uv run black .
uv run ruff check --fix .
```

### Pre-commit hooks

`uv run pre-commit install` once, then every commit runs black, ruff, the
standard whitespace and YAML/TOML checks, a private-key scan, the full test
suite, and a check that this file's contents block is current.

Regenerate the contents after editing a heading:

```bash
uv run python scripts/toc.py
```

### Tests

`pytest` with `asyncio_mode = "auto"`, so an `async def test_` needs no
decorator. Settings are a singleton, and the root `conftest.py` resets it around
every test and points scratch space at a temporary directory.

- Each package keeps its tests in its own `tests/`, and `uv run pytest` at the root runs them all.
- Tests that take the `database` fixture migrate a `nafas_test` database and skip without Postgres.
- GPU services' suites run in their own environments. `make test` runs everything.

## Things that will bite you

**Run one generation of workers per task queue.** Each queue belongs to one
service, so this means one deployed version of that service. Temporal hands
each task to whichever worker is free. Two processes on the same queue built from different
revisions will each decode the other's payloads with its own schema, and a
field the older one does not know about is dropped in silence — no error
anywhere, and the symptom looks intermittent. Before trusting a run after
changing `schemas/`, check what is actually polling:

```bash
docker ps
ps -eo pid,lstart,args | grep -E "nafas_.*(worker|main)"
```

**`localhost` inside a container is the container.** Anything the worker talks
to on the host — Temporal, a local model server — needs the service name or
`host.docker.internal`, not `localhost`.

**Docker Desktop cannot see the GPU.** Its engine runs in a VM. Use the
`Makefile` targets, which pin the native engine, or set `DOCKER_CONTEXT=default`
yourself. A stack started under Docker Desktop and another under the native
engine will fight over the same host ports.

**Guard workflow changes with `workflow.patched()`.** A run already in flight
replays its history across your deploy. It guards workflow *logic*; nothing
guards payload schema drift, which is why the first item exists.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Personal, research, educational and
non-profit use is free. Commercial use of any kind needs a separate written
license from the copyright holder; open an issue or contact omarTBakr to ask.
