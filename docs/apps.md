# Building muGen Applications

muGen is a lightweight microframework designed for developers who need flexibility and customization. It provides foundational components for building applications but does not include built-in solutions for complex, real-world use cases. To address these, developers can extend muGen by adding custom code and functionality. This guide will walk you through setting up a project directory and integrating muGen to start building your application.

## Prerequisites

Before starting, ensure the following:

1. You have a GitHub (or similar) repository set up for source control.

2. You are familiar with basic command-line usage and have Git installed on your system.

## Creating a Downstream Repository

To simplify long-term maintenance, treat your application repository as
downstream and the official `vorsocom/mugen` repository as upstream. The key
principle is: **never modify `mugen/core`**.

### Step 1: Clone muGen

Start from the upstream codebase so your downstream repository has the same
baseline structure and history.

```shell
~$ git clone git@github.com:vorsocom/mugen.git hrms-agent
~$ cd hrms-agent
```

### Step 2: Rewire Remotes

Rename the cloned `origin` remote to `upstream`, then point `origin` to your
new downstream repository.

```shell
~$ git remote rename origin upstream
~$ git remote set-url --push upstream PUSH_DISABLED
~$ git remote add origin [downstream-repo-url]
~$ git remote -v
```

### Step 3: Add Downstream Tracking Metadata

Create a downstream tracking file in the repository root.

```shell
~$ touch downstream.py
```

Populate it with project-specific metadata:

```python
"""Custom metadata for the downstream application."""

__app__ = "My Awesome GenAI App"
__author__ = "Your Name"
__copyright__ = "Project copyright notice"
__email__ = "Project contact email"
__version__ = "0.0.0"
```

### Step 4: Publish Downstream Main and Develop

Commit the downstream tracking file, then push both `main` and `develop` to
your downstream `origin`.

```shell
~$ git add downstream.py
~$ git commit -m "chore: initialize downstream metadata"
~$ git push -u origin main
~$ git checkout -b develop
~$ git push -u origin develop
```

## Downstream Development Boundary

During feature development:

- Keep downstream application logic in `mugen/extension`.
- Leave `mugen/core` unchanged.
- Wire downstream extensions through `mugen.toml`.

This boundary keeps upstream merges small and conflict-resistant.

## Updating Downstream With Upstream Changes

When you need upstream updates, pull `upstream main` while on your downstream
`develop` branch (which fetches and merges in one step).

```shell
~$ git checkout develop
~$ git pull upstream main
~$ git push origin develop
```

## Recommended Guardrails for Downstream Repositories

The baseline flow above works well for small teams. For larger teams or
frequent upstream syncs, add the following safeguards.

### 1) Merge Upstream Through a Sync Branch and PR

Instead of updating `develop` directly, perform upstream integration on a
temporary branch and merge it through code review:

```shell
~$ git checkout develop
~$ git pull origin develop --ff-only
~$ git checkout -b chore/sync-upstream-YYYYMMDD
~$ git pull upstream main
~$ git push -u origin chore/sync-upstream-YYYYMMDD
```

Then open a PR from the sync branch into `develop`.

### 2) Enforce the Core Boundary in CI

Protect `mugen/core` from accidental edits in downstream feature work.
Add a CI check that fails when non-sync PRs include paths under `mugen/core/`.

### 3) Track Upstream Baseline in `downstream.py`

Keep a machine-readable record of the upstream revision used by downstream:

```python
__upstream_repo__ = "vorsocom/mugen"
__upstream_branch__ = "main"
__upstream_sync_ref__ = "vX.Y.Z or <commit-sha>"
```

Update `__upstream_sync_ref__` each time you merge upstream.

### 4) Run Full Gates for Every Upstream Sync

After each upstream merge, run full tests, full E2E validation, and confirm
coverage stays at `100%` before merging to `develop`.

```shell
~$ bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh --python "$(poetry run which python)"
```

### Step 5: Create the muGen Configuration File

muGen requires a configuration file named `mugen.toml` for its settings. Create it by copying a sample file provided in the muGen repository:

```shell
~$ cp conf/mugen.toml.sample mugen.toml
```

The default configurations can be used initially. However, you must configure access credentials for your chosen completion API provider (AWS Bedrock, Cerebras, Groq, OpenAI, Azure AI Foundry, SambaNova, or Vertex). See `docs/gateways.md` for provider-specific options, including Bedrock `Converse`/`InvokeModel` behavior. The default configuration also enables a Telnet client for basic communication with the system.

### Step 6: Create the Hypercorn Configuration File

[Hypercorn](https://github.com/pgjones/hypercorn/) is an ASGI server that runs asynchronous web frameworks like Quart, which muGen is built upon. It can handle concurrent requests efficiently and supports modern web technologies, including HTTP/2 and WebSockets.

To configure Hypercorn, create a `hypercorn.toml` file:

```shell
~$ touch hypercorn.toml
```

Set a bind address to tell Hypercorn where to listen for incoming connections. Edit `hypercorn.toml` and add the following line:

```toml
bind = "127.0.0.1:8081"
```

This configuration specifies that Hypercorn will listen on your local machine (localhost) at port 8081. You can change the address or port later to meet your deployment requirements.

### Step 7: Initialize the Python Environment

muGen uses [Poetry](https://python-poetry.org/) for dependency management. Poetry simplifies the process of installing and managing Python libraries. Make sure Poetry is installed, then run the following commands to set up your environment:

```shell
~$ poetry install  # Install dependencies defined in pyproject.toml

~$ poetry shell    # Activate a virtual environment for your project
```

### Step 8: Run the Application

Now, you can run your muGen application using Hypercorn:

```shell
~$ hypercorn -c hypercorn.toml quartman
```

This command tells Hypercorn to use the configuration file `hypercorn.toml` and run the app exposed by the `quartman` module.

Startup lifecycle:
1. **Phase A (blocking):** bootstrap extensions and register API routes.
2. **Phase B (background):** start long-running platform clients.

Requests are served only after Phase A completes.

### Step 9: Communicate with Your Application

The Telnet client is enabled by default, allowing you to interact with your application. Connect to it on port 8888:

```shell
~$ telnet localhost 8888
```

You should see output similar to:

```text
Trying 127.0.0.1...
Connected to localhost.
Escape character is '^]'.
~ user:
```

At the `~ user:` prompt, type messages to send to the system. Responses from muGen will be prefixed with `~ assistant:`.

## Next Steps

With your application directory set up, you can start [developing extensions for muGen](extensions.md) to add custom functionality, integrate external services, or build new features.
