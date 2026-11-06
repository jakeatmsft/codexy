<p align="center">
  <img src="./assets/logo.svg" alt="Codexy Logo" width="200">
</p>

<h1 align="center">Codexy</h1>
<p align="center">Lightweight coding agent that runs in your terminal (OpenAI Codex CLI Python version)</p>

<p align="center">
  <a href="README_ZH.md">中文文档</a> | <b>English</b>
</p>

<p align="center"><code>python -m pip install -e .</code></p>

![Codexy demo GIF](./assets/codexy-demo.gif)

![Codexy demo 2 GIF](./assets/codexy-demo-2.gif)

---

<details>
<summary><strong>Table of Contents</strong></summary>

- [Original TypeScript Version](#original-typescript-version)
- [Experimental Technology Disclaimer](#experimental-technology-disclaimer)
- [Quickstart](#quickstart)
- [Why Codexy?](#why-codexy)
- [Security Model & Permissions](#securitymodelpermissions)
- [System Requirements](#systemrequirements)
- [CLI Reference](#clireference)
- [Configuration](#configuration)
- [Project Docs](#projectdocs)
- [Contributing](#contributing)
- [License](#license)
- [Zero Data Retention (ZDR) Organization Limitation](#zero-data-retention-zdr-organization-limitation)

</details>

---

## Original TypeScript Version

This project is a Python reimplementation of the original OpenAI Codex CLI, written in TypeScript. You can find the original repository here:

[openai/codex (TypeScript)](https://github.com/openai/codex)

This Python version aims to provide similar functionality using Python tools and libraries.

## Experimental Technology Disclaimer

Codexy (the Python implementation of Codex CLI) is an experimental project under active development. It is not yet stable, may contain bugs, incomplete features, or undergo breaking changes. We're building it in the open with the community and welcome:

- Bug reports
- Feature requests
- Pull requests
- Good vibes

Help us improve by filing issues or submitting PRs (see the Contributing section)!

## Quickstart

Install **this local checkout** with Python 3.10+ and pip:

```shell
python -m pip install -e .
python -m codexy
# Or start with a prompt:
python -m codexy "explain this codebase to me"
```

No new Python dependencies are added; the existing OpenAI SDK requires version 1.75+ for Responses support. If they are already
installed and you want pip to install only Codexy, use
`python -m pip install --no-deps -e .`. The existing `pdm-backend` build requirement
may be installed by pip in an isolated build environment. No uv or Codex CLI is
required. Use `python3` on Linux/WSL or `py` on Windows if needed. For isolation,
create and activate a virtual environment with `python -m venv .venv` first.

### Foundry endpoint and Microsoft Entra authentication

Copy `.env.example` to `.env` if you have not configured it yet, then set your
resource endpoint and **deployment name**:

```dotenv
CODEXY_AUTH_MODE=entra
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=YOUR-DEPLOYMENT
CODEXY_APPROVAL_MODE=suggest
OPENAI_TIMEOUT_MS=60000
CODEXY_CHECK_UPDATES=false
```

A resource endpoint ending in `.services.ai.azure.com` also works. Supply the
resource root or the complete `/openai/v1/` base URL, rather than a Foundry
project URL or a deployment-specific Chat Completions URL. Codexy uses the
OpenAI-compatible v1 Responses API, so no `api-version` setting is needed.
The deployment must support Responses, streaming, and function tools. Codexy keeps tool execution and approvals in Python.

Use an installed Azure CLI to sign in:

```shell
az login
# For a specific tenant:
# az login --tenant YOUR-TENANT-ID
python -m codexy
```

The signed-in identity needs permission to invoke the deployment, such as the
**Cognitive Services OpenAI User** role on the resource. Codexy obtains tokens
with `az account get-access-token` for `https://cognitiveservices.azure.com/`,
caches them in memory, refreshes before expiry, and retries authentication once
after a 401. No Azure Python SDK or additional Python dependency is required. Responses use `store=false`; reasoning context needed for tool continuations stays in memory.
Tokens are not stored in `.env`. The Codex application and its login are not used.

Optional `.env` settings select `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
`AZURE_CONFIG_DIR`, `AZURE_CLI_COMMAND` (an executable path), and
`AZURE_TOKEN_RESOURCE` (for a different Azure cloud/audience). Use Azure CLI
from the same OS user/environment where you signed in. The model picker shows
the configured deployment; `--model` or `CODEXY_MODEL` can select another
existing deployment.

### Optional API-key backend

For an OpenAI-compatible Chat Completions service, configure:

```dotenv
CODEXY_AUTH_MODE=api-key
OPENAI_API_KEY=your-api-key
CODEXY_MODEL=o4-mini
# OPENAI_BASE_URL=https://api.openai.com/v1
```

### Environment configuration

Configuration precedence is CLI flags, exported environment variables, `.env`,
stored JSON/YAML settings, then defaults. Entra mode uses the configured Azure
deployment instead of a stored public model name. `.env` is read from the working
directory on each configuration load. To select another file, export
`CODEXY_ENV_FILE=/absolute/path/to/.env`. `.env` files are ignored by Git.

Besides the settings above, `.env` supports `CODEXY_FULL_STDOUT`,
`CODEXY_DISABLE_PROJECT_DOC`, and `CODEXY_NOTIFY` (`true`/`false`). Automatic PyPI
update checks are disabled by default. `OPENAI_TIMEOUT_MS` must be a positive
integer and controls API requests and Azure CLI token acquisition.

---

## Why Codexy?

Codexy aims to bring the power of the original Codex CLI to the Python ecosystem. It's built for developers who prefer Python tooling or want to integrate agentic coding capabilities into Python workflows.

- **Familiar Python Stack:** Uses common Python libraries like `click`, `textual`, `openai`, `httpx`.
- **Terminal-Native:** Designed for developers who live in the terminal.
- **Agentic Capabilities:** Understands prompts, interacts with code, suggests file edits, and can execute commands.
- **Configurable Approvals:** Control the level of autonomy the agent has.
- **Open Source:** Contribute to its development and see how it works.

---

## Security Model & Permissions

Codexy lets you decide the level of autonomy the agent has via the `--approval-mode` flag (or configuration file). The modes determine what actions require your explicit confirmation:

| Mode                      | What the agent may do without asking                    | Still requires approval                     | Notes                                                                    |
| ------------------------- | ------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------ |
| **Suggest** <br>(default) | • Read files<br>• Run known safe read-only commands¹   | • **All** file edits/writes<br>• Shell commands | Safest mode, requires confirmation for most actions.                     |
| **Auto Edit**             | • Read files<br>• Apply file edits/writes<br>• Safe reads¹ | • Shell commands                            | Automatically modifies files, but asks before running commands.          |
| **Full Auto**             | • Read/write files<br>• Run shell commands²<br>• Safe reads¹ | –                                           | Attempts auto-approval, **BUT sandboxing is NOT YET IMPLEMENTED**.     |
| **Dangerous Auto**        | • Read/write files<br>• Run shell commands              | –                                           | **UNSAFE**. Auto-approves everything without sandboxing. Use with caution. |

¹ *Known safe read-only commands include `ls`, `cat`, `pwd`, `git status`, etc. User-configurable via `safe_commands` in config.*
² *While `full-auto` aims for sandboxed execution, **sandboxing is NOT YET IMPLEMENTED** in this Python version. Commands will run directly.*

**⚠️ Important:** The Python version (`codexy`) currently **lacks the platform-specific sandboxing** (like macOS Seatbelt or Docker/iptables) found in the original TypeScript version. In `full-auto` mode, commands are executed directly on your system without network or filesystem restrictions imposed by the tool itself. The `dangerous-auto` mode explicitly runs everything unsandboxed. Use auto-approval modes with extreme caution, especially outside of trusted environments or version-controlled repositories.

Codexy will show a warning/confirmation if you start in `auto-edit`, `full-auto`, or `dangerous-auto` while the directory is _not_ tracked by Git, so you have a safety net via version control.

---

## System Requirements

| Requirement   | Details                                    |
| ------------- | ------------------------------------------ |
| Operating Sys | Linux, macOS, Windows (cross-platform)     |
| Python        | **3.10 or newer** (see `pyproject.toml`)   |
| pip           | Install the local checkout                  |
| Azure CLI     | Required for Microsoft Entra authentication  |
| Git (optional)| Recommended for safety                     |
| Dependencies  | `click`, `textual`, `openai`, etc.         |

---

## CLI Reference

```
Usage: codexy [OPTIONS] [PROMPT]

  Interactive REPL for Codex agent.

  codexy         Interactive REPL
  codexy "..."   Initial prompt for interactive REPL

Options:
  --model, -m TEXT              Model to use (e.g., o4-mini).
  --image, -i PATH              Path(s) to image files. (Not fully implemented)
  --view, -v PATH               Inspect a saved rollout. (Not implemented)
  --quiet, -q                   Non-interactive mode. (Not implemented)
  --config, -c                  Open instructions file in editor.
  --writable-root, -w PATH      Writable folder (for future sandboxing).
  --approval-mode, -a [suggest|auto-edit|full-auto|dangerous-auto]
                                Override approval policy.
  --auto-edit                   Alias for --approval-mode=auto-edit.
  --full-auto                   Alias for --approval-mode=full-auto.
  --no-project-doc              Do not include codex.md.
  --project-doc PATH            Include additional markdown file.
  --full-stdout                 Do not truncate command output.
  --notify                      Enable desktop notifications. (Not implemented)
  --flex-mode                   Enable "flex-mode" tier. (Not implemented)
  --dangerously-auto-approve-everything
                                Alias for --approval-mode=dangerous-auto.
  --full-context, -f            Full-context mode. (Not implemented)
  --version                     Show the version and exit.
  -h, --help                    Show this message and exit.

Commands:
  completion                    Generate shell completion script.
```

**In-App Commands (within the TUI):**

| Command         | Description                                     |
| --------------- | ----------------------------------------------- |
| `/help`         | Show commands and shortcuts                     |
| `/model`        | Switch LLM model (if before first response)     |
| `/approval`     | Switch auto-approval mode                       |
| `/history`      | Show command history overlay                    |
| `/clear`        | Clear screen and current conversation context   |
| `/clearhistory` | Clear command history file                      |
| `/bug`          | Open browser to file a bug report (Not Implemented) |
| `/compact`      | Condense context summary (Not Implemented)      |
| `q` / `exit`    | Quit the application                            |

---

## Configuration

Codexy looks for configuration files in `~/.codexy/` (note the `codexy` directory name).

-   **`~/.codexy/config.yaml`** (or `.yml`, `.json`): Main configuration.
-   **`~/.codexy/instructions.md`**: Global custom instructions for the agent.
-   **`~/.codexy/history.json`**: Stores command history.

**Example `config.yaml`:**

```yaml
# ~/.codexy/config.yaml
model: o4-mini # Default model to use
approval_mode: suggest # suggest | auto-edit | full-auto | dangerous-auto
full_auto_error_mode: ask-user # ask-user | ignore-and-continue
notify: false # Enable desktop notifications (Not fully implemented)
history:
  max_size: 1000
  save_history: true
safe_commands: # Commands safe to auto-approve in 'suggest' mode
  - git status
  - ls -la
```

**Example `instructions.md`:**

```markdown
- Always use snake_case for Python variables.
- Add type hints to all function definitions.
- Prefer f-strings for formatting.
```

### Memory Compression

To help manage the conversation history and prevent exceeding the model's context length limit, Codexy includes a memory compression feature. When enabled, it automatically compresses older parts of the conversation history.

**How it Works:**

*   The initial system prompt (from `instructions.md` or project docs) is always kept, if present.
*   A configurable number of the most recent messages in the conversation are kept uncompressed.
*   Messages between the initial system prompt and the recent messages are replaced with a single system notification indicating that a portion of the history has been summarized (e.g., `[System: X previous message(s) were summarized due to context length constraints.]`).

**Configuration:**

These settings are configured within the `memory` object in your `~/.codexy/config.json` or `~/.codexy/config.yaml` file.

*   `enable_compression` (boolean):
    *   Set to `true` to enable the memory compression feature.
    *   Default: `false`.
*   `compression_threshold_factor` (float):
    *   A value between 0.0 and 1.0. Compression is triggered when the estimated token count of the current conversation history exceeds this factor multiplied by the model's maximum context window size.
    *   For example, if the model's max tokens is 4096 and this factor is `0.8`, compression will be attempted when the history exceeds approximately 3277 tokens.
    *   Default: `0.8`.
*   `keep_recent_messages` (integer):
    *   The number of most recent messages to always keep uncompressed at the end of the conversation.
    *   Default: `5`.

**Example `config.json`:**

```json
{
  "model": "o4-mini",
  "memory": {
    "enable_compression": true,
    "compression_threshold_factor": 0.75,
    "keep_recent_messages": 10
  }
  // ... other settings
}
```

**Example `config.yaml`:**

```yaml
model: o4-mini
memory:
  enable_compression: true
  compression_threshold_factor: 0.75
  keep_recent_messages: 10
# ... other settings
```

---

## Project Docs

Similar to the original Codex CLI, Codexy can load project-specific context from a `codex.md` (or `.codex.md`, `CODEX.md`) file.

It searches the current directory first, then walks up to the Git root (`.git` directory). If found, its content is appended to your global `instructions.md`.

Disable this behavior with `--no-project-doc` or by setting the environment variable `CODEXY_DISABLE_PROJECT_DOC=1`.

---

## Contributing

Contributions are welcome! Please refer to the main project [CONTRIBUTING guidelines](https://github.com/openai/codex/blob/main/README.md#contributing).

For Python-specific development:

-   This project uses [PDM](https://pdm-project.org/) for dependency management.
-   Install dependencies: `pdm install -G:dev`
-   Run tests: `pdm run pytest`
-   Format code: `pdm run ruff format .`
-   Lint code: `pdm run ruff check .`

---

## License

This project is licensed under the Apache-2.0 License. See the [LICENSE](./LICENSE) file.

---

## Zero Data Retention (ZDR) Organization Limitation

> **Note:** Codexy (Python) currently inherits the same limitation as the original Codex CLI and does **not** support OpenAI organizations with [Zero Data Retention (ZDR)](https://platform.openai.com/docs/guides/your-data#zero-data-retention) enabled due to its reliance on API features incompatible with ZDR. You may encounter 400 errors if your organization uses ZDR.
