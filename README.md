# Nafas

A backend skeleton: FastAPI at the front, Temporal underneath, and the tooling
already wired up. There is no domain code yet — the packages are empty on
purpose, and each one's `__init__.py` says what belongs in it.

## Contents

- [Getting started](#getting-started)
  - [Requirements](#requirements)
  - [Setup](#setup)
- [Running it](#running-it)
  - [The API](#the-api)
  - [The worker](#the-worker)
- [How the code is arranged](#how-the-code-is-arranged)
  - [The layers](#the-layers)
  - [Adding a workflow](#adding-a-workflow)
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
- A Temporal server, once you have a workflow to run. Until then the API and
  the suite need nothing else.

### Setup

```bash
uv sync
uv run pre-commit install     # once, so the hooks run on every commit
cp .env.example .env          # optional: every setting already has a default
```

Check it works:

```bash
uv run pytest
```

## Running it

### The API

```bash
uv run python main.py
```

`GET /health` answers immediately. Routers go in `routes/` and are included in
`main.py`.

### The worker

```bash
uv run python worker.py
```

It registers whatever `workflows.WORKFLOWS` and `activities.ACTIVITIES` hold,
and tells you plainly when that is nothing.

For convenience on a laptop, `RUN_WORKER_IN_API=true` runs the worker inside
the API process instead. Use one or the other, never both — see
[Things that will bite you](#things-that-will-bite-you).

## How the code is arranged

### The layers

The shape is deliberate: logic in the middle, adapters at the edges.

| Package | Holds | Rule |
| --- | --- | --- |
| `routes/` | FastAPI routers | Validate, start or query a workflow, map errors. No logic. |
| `activities/` | Temporal activities | One side effect each, a thin wrapper over `utils`. |
| `workflows/` | Temporal workflows | Decide order. Never do I/O. |
| `schemas/` | Dataclasses crossing a Temporal boundary | Plain dataclasses; they get encoded to JSON. |
| `utils/` | The actual work | No Temporal, no FastAPI. Testable by calling a function. |
| `interfaces/` | Ports to the outside world | A Protocol per dependency, one module per implementation. |
| `prompts/` | Prompts as data | A reviewable diff in one place. |
| `enums/` | Closed vocabularies | A typo becomes an error, not a branch that never matches. |
| `exceptions/` | One hierarchy under `NafasError` | Catch a subtree when the handling is the same. |

The reason for the split is testing: `utils` has no framework imports, so most
of the suite never starts a server or a task queue.

### Adding a workflow

1. `schemas/my_step.py` — a `MyStepInput` and a `MyStepOutput` dataclass.
2. `activities/my_step.py` — an `@activity.defn` that takes the input, calls
   into `utils`, and returns the output.
3. `workflows/my_flow.py` — an `@workflow.defn` class that calls it.
4. Add both to `ACTIVITIES` and `WORKFLOWS` in the package `__init__.py`. The
   worker registers from those lists, so forgetting this is the one mistake
   that fails at runtime rather than at import.
5. `routes/my_flow.py` — a router that starts it and reports status.

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
decorator. Settings are a singleton, and `tests/conftest.py` resets it around
every test and points scratch space at a temporary directory.

## Things that will bite you

**Run one generation of workers per task queue.** Temporal hands each task to
whichever worker is free. Two processes on the same queue built from different
revisions will each decode the other's payloads with its own schema, and a
field the older one does not know about is dropped in silence — no error
anywhere, and the symptom looks intermittent. Before trusting a run after
changing `schemas/`, check what is actually polling:

```bash
docker ps
ps -eo pid,lstart,args | grep -E "worker.py|main.py"
```

**`localhost` inside a container is the container.** Anything the worker talks
to on the host — Temporal, a local model server — needs the service name or
`host.docker.internal`, not `localhost`.

**Guard workflow changes with `workflow.patched()`.** A run already in flight
replays its history across your deploy. It guards workflow *logic*; nothing
guards payload schema drift, which is why the first item exists.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Personal, research, educational and
non-profit use is free. Commercial use of any kind needs a separate written
license from the copyright holder; open an issue or contact omarTBakr to ask.
