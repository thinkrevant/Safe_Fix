# Safe Fix

**A regression-proof protocol for AI-assisted code fixes.**

Safe Fix wraps every code change in a before/after verification loop. It snapshots your project's health before the fix, snapshots again after, and blocks sign-off if anything that was passing is now broken. No fix ships with a new bug.

Works with any language. No dependencies. Just Python 3.7+ stdlib.

## The problem

You ask an AI to fix a vulnerability. It fixes it — and silently breaks two tests, introduces a lint error, or regresses a different feature. You don't notice until production.

Safe Fix makes that impossible. If a fix introduces a regression, the system catches it, blocks the "done" signal, and forces a retry.

## How it works

```
  PRE-SNAPSHOT ──> ANALYZE ──> PLAN ──> IMPLEMENT ──> POST-SNAPSHOT ──> COMPARE
       │                                                                   │
       │                              ┌────────────────────────────────────┘
       │                              │
       │                        Regressions?
       │                         ╱         ╲
       │                       No           Yes
       │                       │             │
       │                  ✅ PASS      Return to ANALYZE
       │                               (max 3 retries)
       └──────────────────────────────────────────────────────────────────────
```

**4 possible outcomes for each check:**

| Status | Meaning |
|--------|---------|
| **STILL PASSING** | Was working, still working. Your fix didn't break this. |
| **IMPROVEMENT** | Was failing, now passing. Your fix solved this. |
| **STILL FAILING** | Was failing before, still failing. Pre-existing — not your fault. |
| **REGRESSION** | Was passing, now failing. **Your fix broke this. Blocked.** |

## Quick start

### 1. Copy into your project

```bash
# Copy the core files into your project
cp -r .safe-fix/ /path/to/your/project/.safe-fix/
```

### 2. Auto-detect your stack (recommended)

```bash
cd /path/to/your/project
python .safe-fix/verifier.py --init --auto
```

This scans your project for `package.json`, `requirements.txt`, `go.mod`, `Cargo.toml`, `Gemfile`, etc. and generates the right `config.json` automatically. It also checks which tools (pytest, eslint, golangci-lint...) are actually installed and skips the ones that aren't.

**Or configure manually** — edit `.safe-fix/config.json` with your real commands:

```json
{
  "checks": {
    "tests": "pytest -q",
    "lint": "flake8 .",
    "security": "bandit -r . -q"
  },
  "watch_patterns": ["**/*.py"]
}
```

### 3. Add to .gitignore

```
.safe-fix/cache/
```

### 4. Use it

Run manually:

```bash
python .safe-fix/verifier.py --pre       # snapshot before
# ... make your changes ...
python .safe-fix/verifier.py --post      # snapshot after
python .safe-fix/verifier.py --compare   # detect regressions
```

## Config examples

<details>
<summary><strong>Python</strong></summary>

```json
{
  "checks": {
    "tests": "pytest -q",
    "lint": "flake8 .",
    "type-check": "mypy .",
    "security": "bandit -r . -q"
  },
  "watch_patterns": ["**/*.py"]
}
```
</details>

<details>
<summary><strong>Node.js / TypeScript</strong></summary>

```json
{
  "checks": {
    "tests": "npm test",
    "lint": "eslint . --max-warnings 0",
    "type-check": "tsc --noEmit",
    "security": "npm audit --audit-level=moderate"
  },
  "watch_patterns": ["**/*.js", "**/*.ts", "**/*.tsx"]
}
```
</details>

<details>
<summary><strong>Go</strong></summary>

```json
{
  "checks": {
    "tests": "go test ./...",
    "lint": "golangci-lint run",
    "vet": "go vet ./...",
    "security": "gosec ./..."
  },
  "watch_patterns": ["**/*.go"]
}
```
</details>

<details>
<summary><strong>Ruby</strong></summary>

```json
{
  "checks": {
    "tests": "bundle exec rspec",
    "lint": "rubocop",
    "security": "bundler-audit"
  },
  "watch_patterns": ["**/*.rb"]
}
```
</details>

<details>
<summary><strong>Rust</strong></summary>

```json
{
  "checks": {
    "tests": "cargo test",
    "lint": "cargo clippy -- -D warnings",
    "security": "cargo audit"
  },
  "watch_patterns": ["**/*.rs"]
}
```
</details>

## CLI reference

| Command | What it does |
|---------|-------------|
| `--init` | Creates default config, cache directory, and .gitignore |
| `--init --auto` | Auto-detects your stack and generates config.json with the right commands |
| `--pre` | Runs all checks, saves results to `pre-state.json` |
| `--post` | Runs all checks, saves results to `post-state.json` |
| `--compare` | Compares snapshots. Exit 0 = safe. Exit 1 = regression or no improvement. |
| `--graph` | Scans imports across all watched files and displays the dependency map |
| `--graph --json` | Same as `--graph` but also exports to `.safe-fix/cache/dependency-graph.json` |
| `--impact FILE` | Shows the blast radius of changing a specific file — every file transitively affected |
| `--history` | Shows fix history — pass/fail timeline, streaks, most-changed files, success rate |
| `--reset` | Deletes cached state files |

## Dependency graph

The verifier can scan your codebase and map which files import which. This tells you — before you touch anything — what the blast radius of a change looks like.

```bash
# See the full dependency map
python .safe-fix/verifier.py --graph

# Check what breaks if you change a specific file
python .safe-fix/verifier.py --impact src/auth.py
```

**Supported languages:** Python, JavaScript, TypeScript, Go, Java, Ruby, Rust, C, C++

The `--impact` command does a full transitive walk. If `A` imports `B` which imports `C`, changing `C` shows both `B` and `A` in the blast radius, with depth levels and a risk rating.

## Auto-detect

Instead of editing `config.json` by hand, let the verifier figure out your stack:

```bash
python .safe-fix/verifier.py --init --auto
```

It looks for marker files in your project root:

| File found | Stack detected | Commands configured |
|-----------|----------------|-------------------|
| `conftest.py`, `pytest.ini` | Python (pytest) | `pytest -q`, `flake8`, `bandit` |
| `package.json` | Node.js | `npm test`, `eslint`, `npm audit` |
| `yarn.lock` | Node.js (yarn) | `yarn test`, `eslint`, `yarn audit` |
| `tsconfig.json` | TypeScript | `tsc --noEmit` (merges with Node.js) |
| `go.mod` | Go | `go test`, `go vet`, `golangci-lint`, `gosec` |
| `Cargo.toml` | Rust | `cargo test`, `cargo clippy`, `cargo audit` |
| `Gemfile` | Ruby | `rspec`, `rubocop`, `bundler-audit` |
| `pom.xml` | Java (Maven) | `mvn test`, `mvn checkstyle:check` |
| `build.gradle` | Java (Gradle) | `gradle test`, `gradle check` |
| `CMakeLists.txt` | C/C++ (CMake) | `cmake --build`, `ctest` |
| `Makefile` | C/C++ (Make) | `make`, `make test` |

It also checks whether each tool is actually installed. Missing tools are listed as skipped — install them later and re-run `--init --auto`.

## Fix history

Every `--compare` run is automatically logged. View the full history with:

```bash
python .safe-fix/verifier.py --history
```

Shows:
- **Timeline** — pass/fail status of every fix cycle, newest first
- **Success rate** — percentage of fix cycles that passed without regressions
- **Streaks** — current and best streak of clean fixes in a row
- **Most changed files** — which files get touched the most across fixes

## The 6-step protocol

The protocol follows these steps:

1. **SNAPSHOT** — Run `--pre` to capture project state
2. **ANALYZE** — Read related code, grep for the same pattern everywhere, trace downstream effects
3. **PLAN** — Document what will change, root cause, and risks
4. **IMPLEMENT** — Apply all changes
5. **VERIFY** — Run `--post` and `--compare`. If regressions: go back to step 2 (max 3 retries)
6. **SIGN OFF** — Only after `--compare` exits 0

## Try the demo

The `examples/vulnerable-app/` directory contains a Python project with 15 intentional bugs and vulnerabilities. Clone the repo, set up the config, and try fixing them — watch the protocol catch regressions in real time.

```bash
cd examples/vulnerable-app
pip install pytest
python -m pytest tests/ -q
# 15 failed, 36 passed — that's the starting state
```

## Honest note

The gate is only as strong as the checks in your `config.json`. If your test suite covers 10% of your code, the verifier can only catch regressions in that 10%. Better tests = stronger guarantee.

This system doesn't write tests for you — it makes sure the tests you already have still pass after every fix.

## License

Apache 2.0 — see [LICENSE](LICENSE).
