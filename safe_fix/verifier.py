#!/usr/bin/env python3
"""
Safe Fix Verifier — captures pre/post state and detects regressions.
Stdlib only, no external dependencies. Python 3.7+.
"""

import argparse
import collections
import datetime
import glob
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import webbrowser

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Paths (defaults — overridden by --project or set_project_root()) ────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
PRE_STATE = os.path.join(CACHE_DIR, "pre-state.json")
POST_STATE = os.path.join(CACHE_DIR, "post-state.json")
ANALYSIS_MD = os.path.join(CACHE_DIR, "analysis.md")
FIX_PLAN_MD = os.path.join(CACHE_DIR, "fix-plan.md")
GRAPH_JSON = os.path.join(CACHE_DIR, "dependency-graph.json")
HISTORY_JSON = os.path.join(CACHE_DIR, "history.json")
GITIGNORE = os.path.join(SCRIPT_DIR, ".gitignore")


def set_project_root(project_path):
    """Re-point all global paths to a different project directory."""
    global PROJECT_ROOT, SCRIPT_DIR, CONFIG_PATH, CACHE_DIR
    global PRE_STATE, POST_STATE, ANALYSIS_MD, FIX_PLAN_MD
    global GRAPH_JSON, HISTORY_JSON, GITIGNORE

    PROJECT_ROOT = os.path.abspath(project_path)
    SCRIPT_DIR = os.path.join(PROJECT_ROOT, ".safe-fix")
    CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
    CACHE_DIR = os.path.join(SCRIPT_DIR, "cache")
    PRE_STATE = os.path.join(CACHE_DIR, "pre-state.json")
    POST_STATE = os.path.join(CACHE_DIR, "post-state.json")
    ANALYSIS_MD = os.path.join(CACHE_DIR, "analysis.md")
    FIX_PLAN_MD = os.path.join(CACHE_DIR, "fix-plan.md")
    GRAPH_JSON = os.path.join(CACHE_DIR, "dependency-graph.json")
    HISTORY_JSON = os.path.join(CACHE_DIR, "history.json")
    GITIGNORE = os.path.join(SCRIPT_DIR, ".gitignore")

# ── Box drawing helpers ─────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

TOP_LEFT = "┌"
TOP_RIGHT = "┐"
BOT_LEFT = "└"
BOT_RIGHT = "┘"
HORIZ = "─"
VERT = "│"
TEE_RIGHT = "├"
TEE_LEFT = "┤"


def box(title, lines, color=CYAN):
    if lines:
        visible_lengths = [
            len(l.replace(GREEN, "").replace(RED, "").replace(YELLOW, "")
                 .replace(CYAN, "").replace(MAGENTA, "").replace(BOLD, "")
                 .replace(DIM, "").replace(RESET, ""))
            for l in lines if l
        ]
        width = max(len(title) + 4, *visible_lengths, 0) + 4
    else:
        width = len(title) + 8
    width = max(width, 50)
    print(f"\n{color}{TOP_LEFT}{HORIZ * (width - 2)}{TOP_RIGHT}{RESET}")
    print(f"{color}{VERT}{RESET} {BOLD}{title}{RESET}{' ' * (width - len(title) - 4)} {color}{VERT}{RESET}")
    print(f"{color}{TEE_RIGHT}{HORIZ * (width - 2)}{TEE_LEFT}{RESET}")
    for line in lines:
        visible = len(line.replace(GREEN, "").replace(RED, "").replace(YELLOW, "")
                        .replace(CYAN, "").replace(MAGENTA, "").replace(BOLD, "")
                        .replace(DIM, "").replace(RESET, ""))
        pad = width - visible - 4
        print(f"{color}{VERT}{RESET} {line}{' ' * max(pad, 0)} {color}{VERT}{RESET}")
    print(f"{color}{BOT_LEFT}{HORIZ * (width - 2)}{BOT_RIGHT}{RESET}")


def header(text, emoji=""):
    width = 56
    print(f"\n{CYAN}{TOP_LEFT}{HORIZ * width}{TOP_RIGHT}{RESET}")
    inner = f" {emoji}  {text}" if emoji else f"  {text}"
    pad = width - len(inner) - 1
    print(f"{CYAN}{VERT}{BOLD}{inner}{RESET}{' ' * max(pad, 0)}{CYAN}{VERT}{RESET}")
    print(f"{CYAN}{BOT_LEFT}{HORIZ * width}{BOT_RIGHT}{RESET}")


# ── Core functions ──────────────────────────────────────────────────────────

def run(cmd):
    """Execute a shell command, return structured result."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=180,
            cwd=PROJECT_ROOT,
        )
        return {
            "cmd": cmd,
            "code": result.returncode,
            "out": result.stdout,
            "err": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "code": -1, "out": "", "err": "TIMEOUT after 180s"}
    except Exception as e:
        return {"cmd": cmd, "code": -1, "out": "", "err": str(e)}


def md5_file(path):
    """Compute MD5 hash of a single file."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


def collect_file_hashes(patterns):
    """Walk watch_patterns and build {relative_path: md5} map."""
    hashes = {}
    project_root = PROJECT_ROOT
    for pattern in patterns:
        full_pattern = os.path.join(project_root, pattern)
        for filepath in glob.glob(full_pattern, recursive=True):
            # skip .safe-fix internals
            if os.path.abspath(filepath).startswith(os.path.abspath(SCRIPT_DIR)):
                continue
            rel = os.path.relpath(filepath, project_root)
            digest = md5_file(filepath)
            if digest:
                hashes[rel] = digest
    return hashes


def load_config():
    """Load config.json, die with a helpful message if missing."""
    if not os.path.exists(CONFIG_PATH):
        print(f"{RED}  Config not found: {CONFIG_PATH}{RESET}")
        print(f"  Run: python {os.path.basename(__file__)} --init")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def capture(label):
    """Run all checks, collect file hashes, return state dict."""
    config = load_config()
    checks = config.get("checks", {})
    patterns = config.get("watch_patterns", [])

    header(f"Capturing state: {label}", "\U0001f4f8")

    results = {}
    for name, cmd in checks.items():
        print(f"\n  {BOLD}{name}{RESET}")
        print(f"  {DIM}$ {cmd}{RESET}")
        r = run(cmd)
        passed = r["code"] == 0
        status = f"{GREEN}✔ PASS{RESET}" if passed else f"{RED}✘ FAIL{RESET}"
        print(f"  {status}  (exit {r['code']})")
        if not passed and r["err"]:
            err_lines = r["err"].strip().splitlines()[:4]
            for el in err_lines:
                print(f"    {DIM}{el}{RESET}")
        results[name] = {
            "cmd": r["cmd"],
            "code": r["code"],
            "passed": passed,
            "out": r["out"],
            "err": r["err"],
        }

    hashes = collect_file_hashes(patterns)

    state = {
        "label": label,
        "timestamp": datetime.datetime.now().isoformat(),
        "results": results,
        "hashes": hashes,
    }
    return state


def save_state(state, path):
    """Write state dict to JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"\n  {GREEN}✔{RESET} Saved to {os.path.relpath(path)}")


# ── Dependency Graph ────────────────────────────────────────────────────────

LANG_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
}

# Regex patterns per language to extract import targets
IMPORT_PATTERNS = {
    "python": [
        re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
        re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE),
    ],
    "javascript": [
        re.compile(r"""import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE),
    ],
    "typescript": [
        re.compile(r"""import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE),
    ],
    "go": [
        re.compile(r'"([^"]+)"', re.MULTILINE),
    ],
    "java": [
        re.compile(r"^\s*import\s+([\w.]+);", re.MULTILINE),
    ],
    "ruby": [
        re.compile(r"""require\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""require_relative\s+['"]([^'"]+)['"]""", re.MULTILINE),
    ],
    "rust": [
        re.compile(r"^\s*use\s+([\w:]+)", re.MULTILINE),
        re.compile(r"^\s*mod\s+(\w+)\s*;", re.MULTILINE),
    ],
    "c": [
        re.compile(r'#include\s+"([^"]+)"', re.MULTILINE),
    ],
    "cpp": [
        re.compile(r'#include\s+"([^"]+)"', re.MULTILINE),
    ],
}


def detect_language(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    return LANG_EXTENSIONS.get(ext)


def parse_imports(filepath, language):
    """Extract raw import strings from a source file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, IOError):
        return []

    patterns = IMPORT_PATTERNS.get(language, [])
    imports = []
    for pat in patterns:
        imports.extend(pat.findall(content))
    return imports


def _ancestor_dirs(filepath):
    """Yield the file's directory and every parent up to (not including) project root."""
    d = os.path.dirname(filepath)
    while d:
        yield d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    yield ""


def resolve_import(raw_import, source_file, language, project_files):
    """Try to resolve a raw import string to a project file path."""
    source_dir = os.path.dirname(source_file)

    candidates = []

    if language == "python":
        parts = raw_import.split(".")
        # try from every ancestor directory (handles nested projects)
        for base_dir in _ancestor_dirs(source_file):
            candidates.append(os.path.join(base_dir, *parts) + ".py")
            candidates.append(os.path.join(base_dir, *parts, "__init__.py"))
        # also try from project root
        candidates.append(os.path.join(*parts) + ".py")
        candidates.append(os.path.join(*parts, "__init__.py"))

    elif language in ("javascript", "typescript"):
        base = raw_import
        if base.startswith("."):
            base = os.path.normpath(os.path.join(source_dir, base))
        suffixes = ["", ".js", ".ts", ".tsx", ".jsx"]
        index_files = ["index.js", "index.ts", "index.tsx"]
        for sfx in suffixes:
            candidates.append(base + sfx)
        for idx in index_files:
            candidates.append(os.path.join(base, idx))

    elif language == "ruby":
        base = raw_import
        if not base.endswith(".rb"):
            base = base + ".rb"
        candidates = [base, os.path.join(source_dir, base)]

    elif language in ("c", "cpp"):
        candidates = [raw_import, os.path.join(source_dir, raw_import)]

    elif language == "go":
        last = raw_import.rstrip("/").split("/")[-1]
        return [f for f in project_files if f.endswith(".go") and last in f]

    elif language == "java":
        parts = raw_import.split(".")
        candidates = [os.path.join(*parts) + ".java"]
        for base_dir in _ancestor_dirs(source_file):
            candidates.append(os.path.join(base_dir, *parts) + ".java")

    elif language == "rust":
        parts = raw_import.replace("::", "/").split("/")
        candidates = [
            os.path.join(*parts) + ".rs",
            os.path.join(*parts, "mod.rs"),
            os.path.join(source_dir, *parts) + ".rs",
        ]
    else:
        return []

    # normalize all candidates and match against known project files
    norm_project = {os.path.normpath(f): f for f in project_files}
    resolved = []
    seen = set()
    for c in candidates:
        nc = os.path.normpath(c)
        if nc in norm_project and nc not in seen:
            resolved.append(norm_project[nc])
            seen.add(nc)
    return resolved


def build_dependency_graph(project_files):
    """Build {file: [files_it_imports]} and {file: [files_that_import_it]}."""
    depends_on = {}    # file -> list of files it imports
    depended_by = {}   # file -> list of files that import it

    for f in project_files:
        depends_on[f] = []
        depended_by[f] = []

    for source in project_files:
        lang = detect_language(source)
        if not lang:
            continue
        full_path = os.path.join(PROJECT_ROOT, source)
        raw_imports = parse_imports(full_path, lang)

        for raw in raw_imports:
            resolved = resolve_import(raw, source, lang, project_files)
            for target in resolved:
                if target != source and target not in depends_on[source]:
                    depends_on[source].append(target)
                    if source not in depended_by[target]:
                        depended_by[target].append(source)

    return depends_on, depended_by


def get_impact_chain(target_file, depended_by, max_depth=10):
    """BFS: find all files transitively affected by changing target_file."""
    visited = set()
    queue = collections.deque()
    queue.append((target_file, 0))
    levels = {}

    while queue:
        current, depth = queue.popleft()
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        levels[current] = depth

        for dependent in depended_by.get(current, []):
            if dependent not in visited:
                queue.append((dependent, depth + 1))

    return levels


def collect_project_files(patterns):
    """Get list of all project files matching watch_patterns."""
    files = []
    for pattern in patterns:
        full_pattern = os.path.join(PROJECT_ROOT, pattern)
        for filepath in glob.glob(full_pattern, recursive=True):
            if os.path.abspath(filepath).startswith(os.path.abspath(SCRIPT_DIR)):
                continue
            rel = os.path.relpath(filepath, PROJECT_ROOT)
            rel = rel.replace("\\", "/")
            files.append(rel)
    return sorted(set(files))


def print_tree(file, depended_by, prefix="", visited=None, max_depth=5, depth=0):
    """Recursively print a tree of dependents."""
    if visited is None:
        visited = set()
    if file in visited or depth > max_depth:
        if file in visited and depended_by.get(file):
            print(f"{prefix}  {DIM}(circular → {file}){RESET}")
        return
    visited.add(file)

    dependents = depended_by.get(file, [])
    for i, dep in enumerate(dependents):
        is_last = i == len(dependents) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "
        count = len(depended_by.get(dep, []))
        suffix = f"  {DIM}(+{count} dependents){RESET}" if count > 0 else ""
        print(f"{prefix}{connector}{CYAN}{dep}{RESET}{suffix}")
        print_tree(dep, depended_by, prefix + child_prefix, visited.copy(), max_depth, depth + 1)


# ── Auto-detect Stack ──────────────────────────────────────────────────────

STACK_SIGNATURES = [
    {
        "name": "Python (pytest)",
        "marker_files": ["pytest.ini", "setup.cfg", "pyproject.toml", "conftest.py"],
        "marker_glob": ["tests/test_*.py", "test_*.py", "**/test_*.py"],
        "checks": {"tests": "python -m pytest -q", "lint": "python -m flake8 .", "security": "python -m bandit -r . -q"},
        "watch": ["**/*.py"],
        "tool_checks": {"tests": "pytest", "lint": "flake8", "security": "bandit"},
    },
    {
        "name": "Python (unittest)",
        "marker_files": ["setup.py", "setup.cfg", "pyproject.toml"],
        "marker_glob": ["tests/test_*.py", "test_*.py", "**/test_*.py"],
        "checks": {"tests": "python -m unittest discover -s tests -q", "lint": "python -m flake8 .", "security": "python -m bandit -r . -q"},
        "watch": ["**/*.py"],
        "tool_checks": {"tests": None, "lint": "flake8", "security": "bandit"},
        "conflicts_with": ["Python (pytest)"],
    },
    {
        "name": "Python (basic)",
        "marker_files": ["requirements.txt", "Pipfile", "pyproject.toml", "setup.py", "setup.cfg"],
        "marker_glob": ["**/*.py"],
        "checks": {},
        "watch": ["**/*.py"],
        "tool_checks": {},
        "fallback": True,
    },
    {
        "name": "Node.js (npm)",
        "marker_files": ["package.json"],
        "checks": {"tests": "npm test", "lint": "npx eslint . --max-warnings 0", "security": "npm audit --audit-level=moderate"},
        "watch": ["**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx"],
        "tool_checks": {"tests": None, "lint": "eslint", "security": None},
    },
    {
        "name": "Node.js (yarn)",
        "marker_files": ["yarn.lock"],
        "checks": {"tests": "yarn test", "lint": "yarn eslint . --max-warnings 0", "security": "yarn audit --level moderate"},
        "watch": ["**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx"],
        "tool_checks": {"tests": None, "lint": "eslint", "security": None},
    },
    {
        "name": "Node.js (pnpm)",
        "marker_files": ["pnpm-lock.yaml"],
        "checks": {"tests": "pnpm test", "lint": "pnpm eslint . --max-warnings 0", "security": "pnpm audit"},
        "watch": ["**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx"],
        "tool_checks": {"tests": None, "lint": "eslint", "security": None},
    },
    {
        "name": "TypeScript",
        "marker_files": ["tsconfig.json"],
        "checks": {"type-check": "npx tsc --noEmit"},
        "watch": ["**/*.ts", "**/*.tsx"],
        "tool_checks": {"type-check": "tsc"},
        "merge": True,
    },
    {
        "name": "Go",
        "marker_files": ["go.mod"],
        "checks": {"tests": "go test ./...", "vet": "go vet ./...", "lint": "golangci-lint run", "security": "gosec ./..."},
        "watch": ["**/*.go"],
        "tool_checks": {"tests": None, "vet": None, "lint": "golangci-lint", "security": "gosec"},
    },
    {
        "name": "Rust",
        "marker_files": ["Cargo.toml"],
        "checks": {"tests": "cargo test", "lint": "cargo clippy -- -D warnings", "security": "cargo audit"},
        "watch": ["**/*.rs"],
        "tool_checks": {"tests": None, "lint": None, "security": "cargo-audit"},
    },
    {
        "name": "Ruby",
        "marker_files": ["Gemfile"],
        "checks": {"tests": "bundle exec rspec", "lint": "bundle exec rubocop", "security": "bundle exec bundler-audit"},
        "watch": ["**/*.rb"],
        "tool_checks": {"tests": "rspec", "lint": "rubocop", "security": "bundler-audit"},
    },
    {
        "name": "Java (Maven)",
        "marker_files": ["pom.xml"],
        "checks": {"tests": "mvn test -q", "lint": "mvn checkstyle:check -q"},
        "watch": ["**/*.java"],
        "tool_checks": {"tests": None, "lint": None},
    },
    {
        "name": "Java (Gradle)",
        "marker_files": ["build.gradle", "build.gradle.kts"],
        "checks": {"tests": "gradle test", "lint": "gradle check"},
        "watch": ["**/*.java", "**/*.kt"],
        "tool_checks": {"tests": None, "lint": None},
    },
    {
        "name": "C/C++ (CMake)",
        "marker_files": ["CMakeLists.txt"],
        "checks": {"build": "cmake --build build", "tests": "ctest --test-dir build"},
        "watch": ["**/*.c", "**/*.cpp", "**/*.h", "**/*.hpp"],
        "tool_checks": {"build": "cmake", "tests": "ctest"},
    },
    {
        "name": "C/C++ (Make)",
        "marker_files": ["Makefile", "makefile"],
        "checks": {"build": "make", "tests": "make test"},
        "watch": ["**/*.c", "**/*.cpp", "**/*.h", "**/*.hpp"],
        "tool_checks": {"build": "make", "tests": None},
    },
]


def _file_exists_in_project(filename):
    return os.path.exists(os.path.join(PROJECT_ROOT, filename))


def _glob_exists_in_project(pattern):
    return bool(glob.glob(os.path.join(PROJECT_ROOT, pattern), recursive=True))


def _tool_available(tool_name):
    if tool_name is None:
        return True
    r = run(f"{'where' if sys.platform == 'win32' else 'which'} {tool_name}")
    return r["code"] == 0


def _check_package_json_scripts():
    """Read package.json and return which npm scripts exist."""
    pkg_path = os.path.join(PROJECT_ROOT, "package.json")
    if not os.path.exists(pkg_path):
        return set()
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
        return set(pkg.get("scripts", {}).keys())
    except (json.JSONDecodeError, OSError):
        return set()


def auto_detect_stack():
    """Scan project root for known files/patterns and return a config dict."""
    detected = []

    for sig in STACK_SIGNATURES:
        matched = False
        for mf in sig.get("marker_files", []):
            if _file_exists_in_project(mf):
                matched = True
                break
        if not matched:
            for mg in sig.get("marker_glob", []):
                if _glob_exists_in_project(mg):
                    matched = True
                    break
        if matched:
            detected.append(sig)

    if not detected:
        return None, [], [], []

    # skip fallback stacks when a real stack for the same watch patterns exists
    real_watches = set()
    for sig in detected:
        if not sig.get("fallback"):
            for w in sig.get("watch", []):
                real_watches.add(w)
    detected = [
        sig for sig in detected
        if not sig.get("fallback") or not any(w in real_watches for w in sig.get("watch", []))
    ]

    # resolve conflicts — drop stacks that conflict with already-detected ones
    detected_names = {sig["name"] for sig in detected}
    detected = [
        sig for sig in detected
        if not any(c in detected_names for c in sig.get("conflicts_with", []))
    ]

    # merge all detected stacks
    checks = {}
    watch = []
    names = []
    available = []
    unavailable = []

    npm_scripts = _check_package_json_scripts()

    for sig in detected:
        names.append(sig["name"])
        watch.extend(sig.get("watch", []))

        sig_checks = sig.get("checks", {})
        tool_checks = sig.get("tool_checks", {})

        for check_name, cmd in sig_checks.items():
            if check_name in checks and not sig.get("merge"):
                continue

            tool = tool_checks.get(check_name)
            is_available = _tool_available(tool)

            # for npm/yarn/pnpm test — check if test script exists
            if check_name == "tests" and cmd in ("npm test", "yarn test", "pnpm test"):
                if "test" not in npm_scripts:
                    unavailable.append((check_name, cmd, "no 'test' script in package.json"))
                    continue

            if is_available:
                checks[check_name] = cmd
                available.append((check_name, cmd, tool or "built-in"))
            else:
                unavailable.append((check_name, cmd, f"'{tool}' not installed"))

    watch = sorted(set(watch))

    config = {"checks": checks, "watch_patterns": watch}
    return config, names, available, unavailable


# ── Bug Scanner Rules ──────────────────────────────────────────────────────

SCAN_RULES = {
    "python": [
        # Security — Critical
        {"id": "PY-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "SQL Injection", "pattern": re.compile(r'''(?:execute|executemany)\s*\(\s*f["']|(?:execute|executemany)\s*\(\s*["'].*%s|(?:execute|executemany)\s*\(\s*.*\.format\(|(?:execute|executemany)\s*\(\s*.*\+\s*(?:['"]|[\w.]+)''', re.MULTILINE),
         "description": "SQL query built with string formatting — vulnerable to SQL injection",
         "fix": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"},
        {"id": "PY-SEC-002", "severity": "CRITICAL", "category": "security",
         "name": "Command Injection", "pattern": re.compile(r'''(?:subprocess\.(?:call|run|Popen|check_output|check_call)\s*\(.*shell\s*=\s*True|os\.system\s*\(|os\.popen\s*\()''', re.MULTILINE),
         "description": "Shell command execution with user-controllable input",
         "fix": "Use subprocess with shell=False and pass args as a list: subprocess.run(['cmd', arg])"},
        {"id": "PY-SEC-003", "severity": "CRITICAL", "category": "security",
         "name": "Hardcoded Secret", "pattern": re.compile(r'''(?:password|secret|api_key|apikey|token|private_key|SECRET_KEY|DB_PASS|AWS_SECRET)\s*=\s*["'][^"']{4,}["']''', re.IGNORECASE | re.MULTILINE),
         "description": "Hardcoded credential or secret in source code",
         "fix": "Use environment variables: os.environ.get('SECRET_KEY')"},
        {"id": "PY-SEC-004", "severity": "CRITICAL", "category": "security",
         "name": "Pickle Deserialization", "pattern": re.compile(r'''pickle\.(?:load|loads)\s*\(''', re.MULTILINE),
         "description": "Deserializing untrusted data with pickle allows arbitrary code execution",
         "fix": "Use json.loads() or a safe serialization format"},
        {"id": "PY-SEC-005", "severity": "CRITICAL", "category": "security",
         "name": "Eval/Exec Usage", "pattern": re.compile(r'''(?<!\w)(?:eval|exec)\s*\(''', re.MULTILINE),
         "description": "eval/exec can execute arbitrary code if input is not trusted",
         "fix": "Use ast.literal_eval() for data parsing, or avoid dynamic code execution"},
        {"id": "PY-SEC-006", "severity": "HIGH", "category": "security",
         "name": "Path Traversal", "pattern": re.compile(r'''open\s*\(.*(?:request|input|argv|args|params|query|filename|filepath|path)''', re.IGNORECASE | re.MULTILINE),
         "description": "File opened with user-supplied path without sanitization",
         "fix": "Validate path with os.path.realpath() and check it stays within allowed directory"},
        {"id": "PY-SEC-007", "severity": "HIGH", "category": "security",
         "name": "Weak Hashing", "pattern": re.compile(r'''(?:hashlib\.md5|hashlib\.sha1|MD5|\.md5\(|\.sha1\()''', re.MULTILINE),
         "description": "MD5/SHA1 used for password hashing or security — cryptographically broken",
         "fix": "Use hashlib.pbkdf2_hmac(), bcrypt, or argon2 for passwords; SHA-256+ for integrity"},
        {"id": "PY-SEC-008", "severity": "HIGH", "category": "security",
         "name": "Insecure Temp File", "pattern": re.compile(r'''(?:tempfile\.mktemp\s*\(|open\s*\(\s*['"]/tmp/)''', re.MULTILINE),
         "description": "Predictable temp file path — vulnerable to symlink attacks",
         "fix": "Use tempfile.mkstemp() or tempfile.NamedTemporaryFile()"},
        {"id": "PY-SEC-009", "severity": "HIGH", "category": "security",
         "name": "YAML Unsafe Load", "pattern": re.compile(r'''yaml\.load\s*\([^)]*(?!\bLoader\b)''', re.MULTILINE),
         "description": "yaml.load() without SafeLoader allows arbitrary code execution",
         "fix": "Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader)"},
        {"id": "PY-SEC-010", "severity": "MEDIUM", "category": "security",
         "name": "Debug Mode Enabled", "pattern": re.compile(r'''(?:DEBUG\s*=\s*True|app\.run\s*\(.*debug\s*=\s*True)''', re.MULTILINE),
         "description": "Debug mode enabled — exposes stack traces and internal state",
         "fix": "Set DEBUG=False in production, use environment variables to control"},
        # Logic bugs
        {"id": "PY-LOG-001", "severity": "MEDIUM", "category": "logic",
         "name": "Division Without Zero Check", "pattern": re.compile(r'''(?:return\s+\w+\s*/\s*\w+|=\s*\w+\s*/\s*\w+)(?!.*(?:if|!=\s*0|> 0|zero))''', re.MULTILINE),
         "description": "Division without checking for zero divisor",
         "fix": "Add a guard: if divisor == 0: raise ValueError('Division by zero')"},
        {"id": "PY-LOG-002", "severity": "MEDIUM", "category": "logic",
         "name": "Empty Collection Access", "pattern": re.compile(r'''(?:\w+\[0\]|\w+\[-1\])(?!.*(?:if\s+\w+|len\s*\(|not\s+\w+))''', re.MULTILINE),
         "description": "Accessing first/last element without checking if collection is empty",
         "fix": "Check length first: if items: return items[0]"},
        {"id": "PY-LOG-003", "severity": "LOW", "category": "logic",
         "name": "Mutable Default Argument", "pattern": re.compile(r'''def\s+\w+\s*\([^)]*=\s*(?:\[\]|\{\}|set\(\))''', re.MULTILINE),
         "description": "Mutable default argument shared across calls",
         "fix": "Use None as default: def func(items=None): items = items or []"},
        {"id": "PY-LOG-004", "severity": "MEDIUM", "category": "logic",
         "name": "Bare Except", "pattern": re.compile(r'''except\s*:''', re.MULTILINE),
         "description": "Bare except catches all exceptions including KeyboardInterrupt and SystemExit",
         "fix": "Catch specific exceptions: except (ValueError, TypeError):"},
        # Code quality
        {"id": "PY-QUA-001", "severity": "LOW", "category": "quality",
         "name": "Wildcard Import", "pattern": re.compile(r'''from\s+\w+(?:\.\w+)*\s+import\s+\*''', re.MULTILINE),
         "description": "Wildcard import pollutes namespace and hides dependencies",
         "fix": "Import specific names: from module import func1, func2"},
        {"id": "PY-QUA-002", "severity": "LOW", "category": "quality",
         "name": "TODO/FIXME/HACK", "pattern": re.compile(r'''#\s*(?:TODO|FIXME|HACK|XXX|BUG)\b''', re.IGNORECASE | re.MULTILINE),
         "description": "Unresolved TODO/FIXME marker in code",
         "fix": "Resolve the issue or create a tracked issue for it"},
        {"id": "PY-QUA-003", "severity": "LOW", "category": "quality",
         "name": "Print Statement in Production", "pattern": re.compile(r'''(?<!\w)print\s*\(''', re.MULTILINE),
         "description": "Print statement — use logging module for production code",
         "fix": "Replace with logging.info(), logging.debug(), etc."},
    ],
    "javascript": [
        {"id": "JS-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "eval() Usage", "pattern": re.compile(r'''(?<!\w)eval\s*\(''', re.MULTILINE),
         "description": "eval() executes arbitrary code — XSS and injection risk",
         "fix": "Use JSON.parse() for data, or avoid dynamic code execution"},
        {"id": "JS-SEC-002", "severity": "CRITICAL", "category": "security",
         "name": "innerHTML Assignment", "pattern": re.compile(r'''\.innerHTML\s*=''', re.MULTILINE),
         "description": "Direct innerHTML assignment — vulnerable to XSS",
         "fix": "Use textContent for text, or sanitize with DOMPurify before inserting HTML"},
        {"id": "JS-SEC-003", "severity": "CRITICAL", "category": "security",
         "name": "Hardcoded Secret", "pattern": re.compile(r'''(?:password|secret|api_key|apikey|token|private_key)\s*[:=]\s*["'][^"']{4,}["']''', re.IGNORECASE | re.MULTILINE),
         "description": "Hardcoded credential or API key in source code",
         "fix": "Use environment variables: process.env.API_KEY"},
        {"id": "JS-SEC-004", "severity": "HIGH", "category": "security",
         "name": "SQL String Concatenation", "pattern": re.compile(r'''(?:query|sql|SELECT|INSERT|UPDATE|DELETE).*[\+`].*(?:req\.|params\.|body\.|query\.)''', re.IGNORECASE | re.MULTILINE),
         "description": "SQL query built with string concatenation — injection risk",
         "fix": "Use parameterized queries or an ORM"},
        {"id": "JS-SEC-005", "severity": "HIGH", "category": "security",
         "name": "No CSRF Protection", "pattern": re.compile(r'''app\.(?:post|put|delete|patch)\s*\(''', re.MULTILINE),
         "description": "State-changing endpoint without visible CSRF protection",
         "fix": "Add CSRF middleware: app.use(csrf())"},
        {"id": "JS-SEC-006", "severity": "MEDIUM", "category": "security",
         "name": "Console.log in Production", "pattern": re.compile(r'''console\.log\s*\(''', re.MULTILINE),
         "description": "Console.log may leak sensitive data in production",
         "fix": "Use a logging library with log levels, strip console.log in builds"},
        {"id": "JS-LOG-001", "severity": "MEDIUM", "category": "logic",
         "name": "== Instead of ===", "pattern": re.compile(r'''(?<![!=<>])={2}(?!=)''', re.MULTILINE),
         "description": "Loose equality (==) causes type coercion bugs",
         "fix": "Use strict equality (===) for predictable comparisons"},
        {"id": "JS-QUA-001", "severity": "LOW", "category": "quality",
         "name": "var Declaration", "pattern": re.compile(r'''(?<!\w)var\s+\w+''', re.MULTILINE),
         "description": "var has function scope — causes hoisting bugs",
         "fix": "Use let or const instead"},
    ],
    "go": [
        {"id": "GO-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "SQL String Formatting", "pattern": re.compile(r'''(?:fmt\.Sprintf|string\s*\+).*(?:SELECT|INSERT|UPDATE|DELETE)''', re.IGNORECASE | re.MULTILINE),
         "description": "SQL query built with fmt.Sprintf — injection risk",
         "fix": "Use parameterized queries: db.Query('SELECT * FROM users WHERE id = $1', id)"},
        {"id": "GO-SEC-002", "severity": "HIGH", "category": "security",
         "name": "Hardcoded Credential", "pattern": re.compile(r'''(?:password|secret|token|apiKey)\s*[:=]\s*"[^"]{4,}"''', re.IGNORECASE | re.MULTILINE),
         "description": "Hardcoded secret in source code",
         "fix": "Use os.Getenv() or a secrets manager"},
        {"id": "GO-LOG-001", "severity": "HIGH", "category": "logic",
         "name": "Unchecked Error", "pattern": re.compile(r'''(?:\w+)\s*,\s*_\s*(?::=|=)\s*\w+\.\w+\(''', re.MULTILINE),
         "description": "Error return value discarded with _ — bugs will be silent",
         "fix": "Check the error: if err != nil { return err }"},
        {"id": "GO-QUA-001", "severity": "LOW", "category": "quality",
         "name": "fmt.Println Debug", "pattern": re.compile(r'''fmt\.Print(?:ln|f)?\s*\(''', re.MULTILINE),
         "description": "fmt.Print in production code — use structured logging",
         "fix": "Use log.Printf() or a structured logging library"},
    ],
    "java": [
        {"id": "JV-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "SQL Injection", "pattern": re.compile(r'''(?:Statement|createStatement|executeQuery|executeUpdate)\s*\(.*["+]''', re.MULTILINE),
         "description": "SQL query built with string concatenation",
         "fix": "Use PreparedStatement with parameter binding"},
        {"id": "JV-SEC-002", "severity": "HIGH", "category": "security",
         "name": "Hardcoded Password", "pattern": re.compile(r'''(?:password|secret|apiKey)\s*=\s*"[^"]{4,}"''', re.IGNORECASE | re.MULTILINE),
         "description": "Hardcoded credential in source code",
         "fix": "Use environment variables or a secrets vault"},
        {"id": "JV-LOG-001", "severity": "MEDIUM", "category": "logic",
         "name": "Empty Catch Block", "pattern": re.compile(r'''catch\s*\([^)]*\)\s*\{\s*\}''', re.MULTILINE),
         "description": "Empty catch block silently swallows exceptions",
         "fix": "Log the exception or rethrow it"},
    ],
    "ruby": [
        {"id": "RB-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "SQL Injection", "pattern": re.compile(r'''(?:where|find_by_sql|execute)\s*\(?\s*["'].*#\{''', re.MULTILINE),
         "description": "SQL query built with string interpolation",
         "fix": "Use parameterized queries: where('name = ?', name)"},
        {"id": "RB-SEC-002", "severity": "CRITICAL", "category": "security",
         "name": "System/Exec Call", "pattern": re.compile(r'''(?:system|exec|`[^`]*`|%x\{)''', re.MULTILINE),
         "description": "Shell command execution — command injection risk",
         "fix": "Use Open3.capture3 or shellescape input"},
        {"id": "RB-SEC-003", "severity": "HIGH", "category": "security",
         "name": "Mass Assignment", "pattern": re.compile(r'''params\.permit!|params\[:?\w+\](?!\.permit)''', re.MULTILINE),
         "description": "Unsanitized params — mass assignment vulnerability",
         "fix": "Use strong parameters: params.require(:user).permit(:name, :email)"},
    ],
    "rust": [
        {"id": "RS-SEC-001", "severity": "HIGH", "category": "security",
         "name": "Unsafe Block", "pattern": re.compile(r'''unsafe\s*\{''', re.MULTILINE),
         "description": "Unsafe block bypasses Rust's memory safety guarantees",
         "fix": "Minimize unsafe usage, document why it's necessary, add safety comments"},
        {"id": "RS-LOG-001", "severity": "MEDIUM", "category": "logic",
         "name": "Unwrap Usage", "pattern": re.compile(r'''\.unwrap\(\)''', re.MULTILINE),
         "description": ".unwrap() panics on None/Err — use proper error handling",
         "fix": "Use .unwrap_or(), .unwrap_or_default(), ? operator, or match"},
    ],
    "c": [
        {"id": "C-SEC-001", "severity": "CRITICAL", "category": "security",
         "name": "Buffer Overflow Risk", "pattern": re.compile(r'''(?:gets\s*\(|strcpy\s*\(|strcat\s*\(|sprintf\s*\()''', re.MULTILINE),
         "description": "Unsafe C function — no bounds checking, buffer overflow risk",
         "fix": "Use fgets(), strncpy(), strncat(), snprintf() instead"},
        {"id": "C-SEC-002", "severity": "HIGH", "category": "security",
         "name": "Format String Vulnerability", "pattern": re.compile(r'''printf\s*\(\s*\w+\s*\)''', re.MULTILINE),
         "description": "User-controlled format string — can read/write arbitrary memory",
         "fix": "Use printf(\"%s\", user_input) instead of printf(user_input)"},
    ],
}
# cpp shares C rules
SCAN_RULES["cpp"] = SCAN_RULES["c"] + [
    {"id": "CPP-QUA-001", "severity": "LOW", "category": "quality",
     "name": "Raw Pointer Usage", "pattern": re.compile(r'''(?<!\w)new\s+\w+''', re.MULTILINE),
     "description": "Raw pointer from new — risk of memory leaks",
     "fix": "Use std::unique_ptr or std::shared_ptr"},
]
# TypeScript shares JS rules
SCAN_RULES["typescript"] = SCAN_RULES["javascript"] + [
    {"id": "TS-QUA-001", "severity": "MEDIUM", "category": "quality",
     "name": "any Type Usage", "pattern": re.compile(r''':\s*any\b''', re.MULTILINE),
     "description": "Using 'any' defeats TypeScript's type safety",
     "fix": "Use a specific type, unknown, or a generic"},
]

EXTERNAL_SCANNERS = {
    "python": [
        {"name": "bandit", "cmd": "python -m bandit -r {dir} -f json -q", "tool": "bandit", "parser": "bandit"},
        {"name": "semgrep", "cmd": "semgrep --config auto {dir} --json -q", "tool": "semgrep", "parser": "semgrep"},
    ],
    "javascript": [
        {"name": "eslint", "cmd": "npx eslint {dir} --format json", "tool": "eslint", "parser": "eslint"},
    ],
    "typescript": [
        {"name": "eslint", "cmd": "npx eslint {dir} --format json", "tool": "eslint", "parser": "eslint"},
    ],
    "go": [
        {"name": "gosec", "cmd": "gosec -fmt=json ./...", "tool": "gosec", "parser": "gosec"},
    ],
}

SCAN_REPORT_JSON = None  # set after paths are resolved


def _resolve_scan_report_path():
    return os.path.join(CACHE_DIR, "scan-report.json")


def scan_file(filepath, language):
    """Scan a single file for bugs using built-in rules. Returns list of findings."""
    rules = SCAN_RULES.get(language, [])
    if not rules:
        return []

    full_path = os.path.join(PROJECT_ROOT, filepath)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            lines = content.splitlines()
    except (OSError, IOError):
        return []

    findings = []
    for rule in rules:
        for match in rule["pattern"].finditer(content):
            line_num = content[:match.start()].count("\n") + 1
            line_text = lines[line_num - 1].strip() if line_num <= len(lines) else ""
            findings.append({
                "id": rule["id"],
                "file": filepath,
                "line": line_num,
                "line_text": line_text,
                "severity": rule["severity"],
                "category": rule["category"],
                "name": rule["name"],
                "description": rule["description"],
                "fix": rule["fix"],
                "source": "built-in",
            })
    return findings


def run_external_scanners(languages):
    """Run available external scanners and parse their output."""
    findings = []
    seen_tools = set()

    for lang in languages:
        scanners = EXTERNAL_SCANNERS.get(lang, [])
        for scanner in scanners:
            if scanner["name"] in seen_tools:
                continue
            if not _tool_available(scanner["tool"]):
                continue
            seen_tools.add(scanner["name"])

            cmd = scanner["cmd"].replace("{dir}", ".")
            print(f"  {DIM}Running {scanner['name']}...{RESET}")
            r = run(cmd)
            if r["code"] != 0 and not r["out"]:
                continue

            try:
                data = json.loads(r["out"])
            except (json.JSONDecodeError, ValueError):
                continue

            if scanner["parser"] == "bandit":
                for result in data.get("results", []):
                    sev = result.get("issue_severity", "MEDIUM").upper()
                    findings.append({
                        "id": f"BANDIT-{result.get('test_id', '?')}",
                        "file": os.path.relpath(result.get("filename", "?"), PROJECT_ROOT),
                        "line": result.get("line_number", 0),
                        "line_text": (result.get("code", "").strip().splitlines() or [""])[0][:120],
                        "severity": sev if sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "MEDIUM",
                        "category": "security",
                        "name": result.get("test_name", result.get("test_id", "?")),
                        "description": result.get("issue_text", ""),
                        "fix": f"See: {result.get('more_info', '')}",
                        "source": "bandit",
                    })
            elif scanner["parser"] == "semgrep":
                for result in data.get("results", []):
                    sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
                    sev = sev_map.get(result.get("extra", {}).get("severity", ""), "MEDIUM")
                    findings.append({
                        "id": result.get("check_id", "SEMGREP-?"),
                        "file": os.path.relpath(result.get("path", "?"), PROJECT_ROOT),
                        "line": result.get("start", {}).get("line", 0),
                        "line_text": (result.get("extra", {}).get("lines", "").strip().splitlines() or [""])[0][:120],
                        "severity": sev,
                        "category": "security",
                        "name": result.get("check_id", "").split(".")[-1],
                        "description": result.get("extra", {}).get("message", ""),
                        "fix": f"See: {result.get('extra', {}).get('metadata', {}).get('references', [''])[0]}",
                        "source": "semgrep",
                    })
            elif scanner["parser"] == "eslint":
                for file_result in (data if isinstance(data, list) else []):
                    for msg in file_result.get("messages", []):
                        sev = "HIGH" if msg.get("severity", 1) >= 2 else "MEDIUM"
                        findings.append({
                            "id": f"ESLINT-{msg.get('ruleId', '?')}",
                            "file": os.path.relpath(file_result.get("filePath", "?"), PROJECT_ROOT),
                            "line": msg.get("line", 0),
                            "line_text": msg.get("source", "")[:120],
                            "severity": sev,
                            "category": "quality",
                            "name": msg.get("ruleId", "?"),
                            "description": msg.get("message", ""),
                            "fix": f"ESLint rule: {msg.get('ruleId', '?')}",
                            "source": "eslint",
                        })
            elif scanner["parser"] == "gosec":
                for issue in data.get("Issues", []):
                    sev = issue.get("severity", "MEDIUM").upper()
                    findings.append({
                        "id": f"GOSEC-{issue.get('rule_id', '?')}",
                        "file": issue.get("file", "?"),
                        "line": int(issue.get("line", 0)),
                        "line_text": issue.get("code", "")[:120],
                        "severity": sev if sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "MEDIUM",
                        "category": "security",
                        "name": issue.get("details", "?")[:60],
                        "description": issue.get("details", ""),
                        "fix": f"See: {issue.get('cwe', {}).get('url', '')}",
                        "source": "gosec",
                    })

    return findings


def deduplicate_findings(findings):
    """Remove duplicate findings (same file, line, and rule name)."""
    seen = set()
    unique = []
    for f in findings:
        key = (f["file"], f["line"], f["name"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


# ── Fix History ────────────────────────────────────────────────────────────

def load_history():
    if os.path.exists(HISTORY_JSON):
        with open(HISTORY_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"fixes": []}


def save_history(history):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def record_fix(pre_state, post_state, comparison):
    """Append a fix record to history.json after a successful --compare."""
    history = load_history()

    pre_hashes = pre_state.get("hashes", {})
    post_hashes = post_state.get("hashes", {})
    all_files = set(list(pre_hashes.keys()) + list(post_hashes.keys()))

    files_added = [f for f in sorted(all_files) if f not in pre_hashes]
    files_removed = [f for f in sorted(all_files) if f not in post_hashes]
    files_modified = [f for f in sorted(all_files) if f in pre_hashes and f in post_hashes and pre_hashes[f] != post_hashes[f]]

    record = {
        "id": len(history["fixes"]) + 1,
        "timestamp": datetime.datetime.now().isoformat(),
        "pre_timestamp": pre_state.get("timestamp"),
        "post_timestamp": post_state.get("timestamp"),
        "result": comparison["result"],
        "regressions": comparison["regressions"],
        "improvements": comparison["improvements"],
        "still_passing": comparison["still_passing"],
        "still_failing": comparison["still_failing"],
        "files_added": files_added,
        "files_removed": files_removed,
        "files_modified": files_modified,
    }

    history["fixes"].append(record)
    save_history(history)
    return record


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_init(auto=False):
    """Create default config, cache dir, and .gitignore."""
    header("Initializing Safe Fix", "\U0001f680")

    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"  {GREEN}✔{RESET} Created cache directory")

    if auto:
        print(f"\n  {CYAN}Scanning project for stack...{RESET}")
        result = auto_detect_stack()
        if result[0] is None:
            print(f"  {YELLOW}No known stack detected. Falling back to default config.{RESET}")
            auto = False
        else:
            config, names, available, unavailable = result

            # show what we found
            name_lines = [f"  {GREEN}✔{RESET} {n}" for n in names]
            box("Detected Stacks", name_lines, GREEN)

            # show available checks
            if available:
                avail_lines = []
                for check_name, cmd, tool in available:
                    avail_lines.append(f"  {GREEN}✔{RESET} {BOLD}{check_name}{RESET}: {DIM}{cmd}{RESET}")
                box("Checks configured", avail_lines, GREEN)

            # show unavailable checks
            if unavailable:
                unavail_lines = []
                for check_name, cmd, reason in unavailable:
                    unavail_lines.append(f"  {YELLOW}⚠{RESET}  {BOLD}{check_name}{RESET}: {DIM}{cmd}{RESET}")
                    unavail_lines.append(f"     {DIM}skipped — {reason}{RESET}")
                box("Checks skipped (tools not found)", unavail_lines, YELLOW)

            # write config
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"\n  {GREEN}✔{RESET} Generated config.json for: {', '.join(names)}")

    if not auto:
        if not os.path.exists(CONFIG_PATH):
            default_config = {
                "_instructions": "Replace the echo commands with your real commands. Remove keys you do not need. Add extra keys for more checks.",
                "checks": {
                    "tests": "echo replace with your test command",
                    "lint": "echo replace with your lint command",
                    "security": "echo replace with your security scan command",
                },
                "watch_patterns": [
                    "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx",
                    "**/*.go", "**/*.java", "**/*.rb", "**/*.rs",
                    "**/*.c", "**/*.cpp",
                ],
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            print(f"  {GREEN}✔{RESET} Created default config.json")
        else:
            print(f"  {YELLOW}⚠{RESET}  config.json already exists, skipping")

    gitignore_content = "cache/\n"
    with open(GITIGNORE, "w", encoding="utf-8") as f:
        f.write(gitignore_content)
    print(f"  {GREEN}✔{RESET} Created .gitignore (ignores cache/)")

    if not auto:
        print(f"\n  {BOLD}Next steps:{RESET}")
        print(f"  1. Edit {os.path.relpath(CONFIG_PATH)} with your real commands")
        print(f"  2. Add .safe-fix/cache/ to your project .gitignore")
        print(f"  3. Run: python {os.path.relpath(__file__)} --pre")
    else:
        print(f"\n  {BOLD}Next steps:{RESET}")
        if unavailable:
            print(f"  1. Install missing tools to enable skipped checks")
            print(f"  2. Or edit {os.path.relpath(CONFIG_PATH)} to customize")
        else:
            print(f"  1. Review {os.path.relpath(CONFIG_PATH)} if you want to customize")
        print(f"  {'2' if not unavailable else '3'}. Add .safe-fix/cache/ to your project .gitignore")
        print(f"  {'3' if not unavailable else '4'}. Run: python {os.path.relpath(__file__)} --pre")
    print()


def cmd_pre():
    """Capture pre-fix state."""
    state = capture("pre-fix")
    save_state(state, PRE_STATE)

    total = len(state["results"])
    passed = sum(1 for r in state["results"].values() if r["passed"])
    failed = total - passed
    files = len(state["hashes"])

    lines = [
        f"Checks: {passed} passed, {failed} failed, {total} total",
        f"Files tracked: {files}",
        f"Saved: pre-state.json",
    ]
    box("Pre-fix snapshot complete", lines, GREEN if failed == 0 else YELLOW)


def cmd_post():
    """Capture post-fix state."""
    state = capture("post-fix")
    save_state(state, POST_STATE)

    total = len(state["results"])
    passed = sum(1 for r in state["results"].values() if r["passed"])
    failed = total - passed
    files = len(state["hashes"])

    lines = [
        f"Checks: {passed} passed, {failed} failed, {total} total",
        f"Files tracked: {files}",
        f"Saved: post-state.json",
    ]
    box("Post-fix snapshot complete", lines, GREEN if failed == 0 else YELLOW)


def cmd_compare():
    """Compare pre and post states, detect regressions."""
    header("Comparing snapshots", "\U0001f50d")

    if not os.path.exists(PRE_STATE):
        print(f"  {RED}✘ Missing pre-state.json. Run --pre first.{RESET}")
        sys.exit(1)
    if not os.path.exists(POST_STATE):
        print(f"  {RED}✘ Missing post-state.json. Run --post first.{RESET}")
        sys.exit(1)

    with open(PRE_STATE, "r", encoding="utf-8") as f:
        pre = json.load(f)
    with open(POST_STATE, "r", encoding="utf-8") as f:
        post = json.load(f)

    # ── Check comparison ────────────────────────────────────────────────
    all_checks = set(list(pre["results"].keys()) + list(post["results"].keys()))
    regressions = []
    improvements = []
    still_passing = []
    still_failing = []

    check_lines = []
    for name in sorted(all_checks):
        pre_r = pre["results"].get(name, {})
        post_r = post["results"].get(name, {})
        pre_pass = pre_r.get("passed", False)
        post_pass = post_r.get("passed", False)

        if pre_pass and post_pass:
            status = f"{GREEN}✔ STILL PASSING{RESET}"
            still_passing.append(name)
        elif not pre_pass and post_pass:
            status = f"{GREEN}⬆ IMPROVEMENT{RESET}"
            improvements.append(name)
        elif not pre_pass and not post_pass:
            status = f"{YELLOW}○ STILL FAILING{RESET}"
            still_failing.append(name)
        else:
            status = f"{RED}\U0001f6a8 REGRESSION{RESET}"
            regressions.append(name)

        check_lines.append(f"  {status}  {BOLD}{name}{RESET}")

    box("Check Results", check_lines)

    # ── Show regression details ─────────────────────────────────────────
    if regressions:
        reg_lines = []
        for name in regressions:
            post_r = post["results"].get(name, {})
            reg_lines.append(f"{RED}{BOLD}{name}{RESET}")
            reg_lines.append(f"  Command: {post_r.get('cmd', '?')}")
            reg_lines.append(f"  Exit code: {post_r.get('code', '?')}")
            if post_r.get("err"):
                reg_lines.append(f"  Error output:")
                for el in post_r["err"].strip().splitlines()[:6]:
                    reg_lines.append(f"    {DIM}{el}{RESET}")
            reg_lines.append("")
        box("\U0001f6a8 REGRESSIONS DETECTED", reg_lines, RED)

    # ── File diff ───────────────────────────────────────────────────────
    pre_hashes = pre.get("hashes", {})
    post_hashes = post.get("hashes", {})
    all_files = set(list(pre_hashes.keys()) + list(post_hashes.keys()))

    added = []
    removed = []
    modified = []
    unchanged = []

    for f in sorted(all_files):
        pre_h = pre_hashes.get(f)
        post_h = post_hashes.get(f)
        if pre_h is None and post_h is not None:
            added.append(f)
        elif pre_h is not None and post_h is None:
            removed.append(f)
        elif pre_h != post_h:
            modified.append(f)
        else:
            unchanged.append(f)

    file_lines = []
    for f in added:
        file_lines.append(f"  {GREEN}+ {f}{RESET}")
    for f in removed:
        file_lines.append(f"  {RED}- {f}{RESET}")
    for f in modified:
        file_lines.append(f"  {YELLOW}~ {f}{RESET}")
    if unchanged:
        file_lines.append(f"  {DIM}  {len(unchanged)} file(s) unchanged{RESET}")

    if file_lines:
        box("File Changes", file_lines, MAGENTA)
    else:
        box("File Changes", [f"  {DIM}No tracked files found{RESET}"], MAGENTA)

    # ── Summary ─────────────────────────────────────────────────────────
    print()
    summary_parts = []
    if still_passing:
        summary_parts.append(f"{GREEN}{len(still_passing)} still passing{RESET}")
    if improvements:
        summary_parts.append(f"{GREEN}{len(improvements)} improved{RESET}")
    if still_failing:
        summary_parts.append(f"{YELLOW}{len(still_failing)} pre-existing{RESET}")
    if regressions:
        summary_parts.append(f"{RED}{len(regressions)} regression(s){RESET}")

    print(f"  Summary: {', '.join(summary_parts)}")
    print(f"  Files: {len(added)} added, {len(removed)} removed, {len(modified)} modified")
    print()

    # ── Verdict ─────────────────────────────────────────────────────────
    comparison = {
        "result": "unknown",
        "regressions": regressions,
        "improvements": improvements,
        "still_passing": still_passing,
        "still_failing": still_failing,
    }

    if regressions:
        comparison["result"] = "FAILED_REGRESSION"
        record_fix(pre, post, comparison)
        print(f"  {RED}{BOLD}\U0001f6a8 VERIFICATION FAILED — {len(regressions)} regression(s) detected{RESET}")
        print(f"  {RED}Fix the regressions before signing off.{RESET}")
        print()
        sys.exit(1)

    if not improvements:
        comparison["result"] = "FAILED_NO_IMPROVEMENT"
        record_fix(pre, post, comparison)
        print(f"  {YELLOW}{BOLD}⚠  VERIFICATION FAILED — no improvements detected{RESET}")
        print(f"  {YELLOW}The fix did not change any check from FAIL to PASS.{RESET}")
        print()
        sys.exit(1)

    comparison["result"] = "PASSED"
    record = record_fix(pre, post, comparison)
    print(f"  {GREEN}{BOLD}✅ VERIFICATION PASSED{RESET}")
    print(f"  {GREEN}No regressions. {len(improvements)} check(s) improved.{RESET}")
    print(f"  {DIM}Recorded as fix #{record['id']} in history.{RESET}")
    print()
    sys.exit(0)


def generate_visual_graph(files, depends_on, depended_by):
    """Generate an interactive HTML dependency graph and open in browser."""
    nodes = []
    edges = []
    node_index = {f: i for i, f in enumerate(files)}

    for idx, f in enumerate(files):
        dep_count = len(depends_on.get(f, []))
        dependent_count = len(depended_by.get(f, []))
        total = dep_count + dependent_count
        name = os.path.basename(f)
        directory = os.path.dirname(f) or "."
        nodes.append({
            "id": idx, "file": f, "name": name, "dir": directory,
            "imports": dep_count, "importedBy": dependent_count, "total": total,
        })

    for source, targets in depends_on.items():
        for target in targets:
            if source in node_index and target in node_index:
                edges.append({"source": node_index[source], "target": node_index[target]})

    graph_data = json.dumps({"nodes": nodes, "edges": edges})

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Safe Fix — Dependency Graph</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; overflow: hidden; }}
canvas {{ display: block; cursor: grab; }}
canvas:active {{ cursor: grabbing; }}
#info {{ position: fixed; top: 16px; left: 16px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; max-width: 320px; font-size: 13px; z-index: 10; }}
#info h2 {{ font-size: 15px; margin-bottom: 8px; color: #58a6ff; }}
#info p {{ margin: 4px 0; color: #8b949e; }}
#info .stat {{ color: #c9d1d9; }}
#tooltip {{ position: fixed; background: #1c2128; border: 1px solid #30363d; border-radius: 6px; padding: 12px; font-size: 12px; pointer-events: none; display: none; z-index: 20; max-width: 350px; }}
#tooltip .file {{ color: #58a6ff; font-weight: 600; font-size: 13px; }}
#tooltip .dir {{ color: #8b949e; font-size: 11px; }}
#tooltip .stats {{ margin-top: 6px; }}
#tooltip .stats span {{ display: inline-block; margin-right: 12px; }}
#tooltip .imp {{ color: #3fb950; }}
#tooltip .dep {{ color: #f0883e; }}
#legend {{ position: fixed; bottom: 16px; left: 16px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 16px; font-size: 12px; z-index: 10; }}
#legend span {{ margin-right: 16px; }}
#legend .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
#search {{ position: fixed; top: 16px; right: 16px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px 12px; color: #c9d1d9; font-size: 13px; width: 220px; outline: none; z-index: 10; }}
#search:focus {{ border-color: #58a6ff; }}
#search::placeholder {{ color: #484f58; }}
</style>
</head>
<body>
<canvas id="canvas"></canvas>
<div id="info">
<h2>Dependency Graph</h2>
<p><span class="stat">{len(files)}</span> files &middot; <span class="stat">{len(edges)}</span> connections</p>
<p style="margin-top:8px;color:#8b949e;font-size:11px;">Drag to pan &middot; Scroll to zoom &middot; Hover for details</p>
</div>
<input id="search" type="text" placeholder="Search files...">
<div id="tooltip"></div>
<div id="legend">
<span><span class="dot" style="background:#f0883e"></span> Hub (many dependents)</span>
<span><span class="dot" style="background:#58a6ff"></span> Normal</span>
<span><span class="dot" style="background:#30363d"></span> Isolated</span>
</div>
<script>
const data = {graph_data};
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const searchInput = document.getElementById('search');

let W, H;
function resize() {{ W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight; }}
resize();
window.addEventListener('resize', () => {{ resize(); draw(); }});

const nodes = data.nodes;
const edges = data.edges;
const N = nodes.length;

// layout: force-directed simulation
const rng = (s) => {{ s = Math.sin(s * 127.1) * 43758.5453; return s - Math.floor(s); }};
nodes.forEach((n, i) => {{
    n.x = W/2 + (rng(i*3+1) - 0.5) * Math.min(W, H) * 0.6;
    n.y = H/2 + (rng(i*3+2) - 0.5) * Math.min(W, H) * 0.6;
    n.vx = 0; n.vy = 0;
    n.radius = Math.max(6, Math.min(20, 6 + n.total * 2));
}});

function simulate() {{
    const alpha = 0.3;
    // repulsion
    for (let i = 0; i < N; i++) {{
        for (let j = i + 1; j < N; j++) {{
            let dx = nodes[j].x - nodes[i].x;
            let dy = nodes[j].y - nodes[i].y;
            let d = Math.sqrt(dx*dx + dy*dy) || 1;
            let force = -800 / (d * d);
            let fx = dx / d * force;
            let fy = dy / d * force;
            nodes[i].vx -= fx; nodes[i].vy -= fy;
            nodes[j].vx += fx; nodes[j].vy += fy;
        }}
    }}
    // attraction (edges)
    edges.forEach(e => {{
        let s = nodes[e.source], t = nodes[e.target];
        let dx = t.x - s.x, dy = t.y - s.y;
        let d = Math.sqrt(dx*dx + dy*dy) || 1;
        let force = (d - 120) * 0.01;
        let fx = dx / d * force, fy = dy / d * force;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
    }});
    // center gravity
    nodes.forEach(n => {{
        n.vx += (W/2 - n.x) * 0.001;
        n.vy += (H/2 - n.y) * 0.001;
        n.vx *= 0.85; n.vy *= 0.85;
        n.x += n.vx * alpha; n.y += n.vy * alpha;
    }});
}}

// run initial simulation
for (let i = 0; i < 200; i++) simulate();

let panX = 0, panY = 0, scale = 1;
let dragging = false, lastX, lastY;
let hovered = null;
let searchTerm = '';

canvas.addEventListener('mousedown', e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
canvas.addEventListener('mousemove', e => {{
    if (dragging) {{
        panX += e.clientX - lastX; panY += e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        draw();
    }} else {{
        const mx = (e.clientX - panX) / scale;
        const my = (e.clientY - panY) / scale;
        hovered = null;
        for (let i = N - 1; i >= 0; i--) {{
            const dx = nodes[i].x - mx, dy = nodes[i].y - my;
            if (dx*dx + dy*dy < nodes[i].radius * nodes[i].radius * 1.5) {{
                hovered = i; break;
            }}
        }}
        if (hovered !== null) {{
            const n = nodes[hovered];
            tooltip.style.display = 'block';
            tooltip.style.left = (e.clientX + 16) + 'px';
            tooltip.style.top = (e.clientY + 16) + 'px';
            tooltip.innerHTML = '<div class="file">' + n.name + '</div>'
                + '<div class="dir">' + n.file + '</div>'
                + '<div class="stats">'
                + '<span class="imp">imports: ' + n.imports + '</span>'
                + '<span class="dep">imported by: ' + n.importedBy + '</span>'
                + '</div>';
        }} else {{
            tooltip.style.display = 'none';
        }}
        draw();
    }}
}});
canvas.addEventListener('mouseup', () => {{ dragging = false; }});
canvas.addEventListener('wheel', e => {{
    e.preventDefault();
    const zoom = e.deltaY > 0 ? 0.9 : 1.1;
    const mx = e.clientX, my = e.clientY;
    panX = mx - (mx - panX) * zoom;
    panY = my - (my - panY) * zoom;
    scale *= zoom;
    draw();
}}, {{ passive: false }});

searchInput.addEventListener('input', e => {{
    searchTerm = e.target.value.toLowerCase();
    draw();
}});

function nodeColor(n, idx) {{
    if (searchTerm && !n.file.toLowerCase().includes(searchTerm) && !n.name.toLowerCase().includes(searchTerm))
        return 'rgba(48,54,61,0.4)';
    if (hovered !== null) {{
        if (idx === hovered) return '#f78166';
        const isConn = edges.some(e =>
            (e.source === hovered && e.target === idx) ||
            (e.target === hovered && e.source === idx));
        if (isConn) return '#3fb950';
        return 'rgba(88,166,255,0.25)';
    }}
    if (n.total === 0) return '#30363d';
    if (n.importedBy >= 3) return '#f0883e';
    return '#58a6ff';
}}

function draw() {{
    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(panX, panY);
    ctx.scale(scale, scale);

    // edges
    edges.forEach(e => {{
        const s = nodes[e.source], t = nodes[e.target];
        let alpha = 0.25;
        let color = '88,166,255';
        if (hovered !== null) {{
            if (e.source === hovered || e.target === hovered) {{
                alpha = 0.8; color = '63,185,80';
            }} else {{
                alpha = 0.06;
            }}
        }}
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = 'rgba(' + color + ',' + alpha + ')';
        ctx.lineWidth = hovered !== null && (e.source === hovered || e.target === hovered) ? 2 : 1;
        ctx.stroke();

        // arrowhead
        if (alpha > 0.1) {{
            const dx = t.x - s.x, dy = t.y - s.y;
            const d = Math.sqrt(dx*dx + dy*dy) || 1;
            const ux = dx/d, uy = dy/d;
            const ax = t.x - ux * (t.radius + 4), ay = t.y - uy * (t.radius + 4);
            const sz = 6;
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.lineTo(ax - ux*sz - uy*sz*0.5, ay - uy*sz + ux*sz*0.5);
            ctx.lineTo(ax - ux*sz + uy*sz*0.5, ay - uy*sz - ux*sz*0.5);
            ctx.closePath();
            ctx.fillStyle = 'rgba(' + color + ',' + alpha + ')';
            ctx.fill();
        }}
    }});

    // nodes
    nodes.forEach((n, i) => {{
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fillStyle = nodeColor(n, i);
        ctx.fill();
        if (i === hovered) {{
            ctx.strokeStyle = '#f78166';
            ctx.lineWidth = 2;
            ctx.stroke();
        }}
    }});

    // labels
    const showLabels = scale > 0.5;
    if (showLabels) {{
        ctx.font = (11 / Math.max(scale, 0.5)) + 'px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        nodes.forEach((n, i) => {{
            if (searchTerm && !n.file.toLowerCase().includes(searchTerm) && !n.name.toLowerCase().includes(searchTerm))
                return;
            let show = hovered === null || i === hovered ||
                edges.some(e => (e.source === hovered && e.target === i) || (e.target === hovered && e.source === i));
            if (!show && scale < 1.2 && N > 20) return;
            ctx.fillStyle = i === hovered ? '#f78166' : 'rgba(201,209,217,0.8)';
            ctx.fillText(n.name, n.x, n.y + n.radius + 14);
        }});
    }}

    ctx.restore();
}}

draw();
</script>
</body>
</html>"""

    graph_html_path = os.path.join(CACHE_DIR, "dependency-graph.html")
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(graph_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  {GREEN}✔{RESET} Visual graph saved to {os.path.relpath(graph_html_path)}")
    print(f"  {CYAN}Opening in browser...{RESET}")
    webbrowser.open("file://" + os.path.abspath(graph_html_path).replace("\\", "/"))
    return graph_html_path


def cmd_graph(export_json=False, visual=False):
    """Build and display the full dependency graph."""
    header("Dependency Graph", "\U0001f578️")

    config = load_config()
    patterns = config.get("watch_patterns", [])
    files = collect_project_files(patterns)

    if not files:
        print(f"  {YELLOW}No files found matching watch_patterns.{RESET}")
        print()
        return

    depends_on, depended_by = build_dependency_graph(files)

    # find files with connections
    connected = {f for f in files if depends_on[f] or depended_by[f]}
    isolated = [f for f in files if f not in connected]

    # ── Stats ───────────────────────────────────────────────────────────
    total_edges = sum(len(deps) for deps in depends_on.values())
    most_deps = sorted(files, key=lambda f: len(depends_on[f]), reverse=True)
    most_dependents = sorted(files, key=lambda f: len(depended_by[f]), reverse=True)

    stat_lines = [
        f"Files scanned: {BOLD}{len(files)}{RESET}",
        f"Connections found: {BOLD}{total_edges}{RESET}",
        f"Connected files: {BOLD}{len(connected)}{RESET}",
        f"Isolated files: {BOLD}{len(isolated)}{RESET}",
    ]
    box("Overview", stat_lines)

    # ── Dependency map ──────────────────────────────────────────────────
    if connected:
        dep_lines = []
        for f in sorted(connected):
            imports = depends_on[f]
            importers = depended_by[f]
            dep_lines.append(f"{BOLD}{f}{RESET}")
            if imports:
                dep_lines.append(f"  {GREEN}imports:{RESET} {', '.join(imports)}")
            if importers:
                dep_lines.append(f"  {YELLOW}imported by:{RESET} {', '.join(importers)}")
            dep_lines.append("")
        box("Dependency Map", dep_lines, CYAN)

    # ── Most connected ──────────────────────────────────────────────────
    hub_lines = []
    hub_lines.append(f"  {BOLD}Most dependencies (imports the most):{RESET}")
    for f in most_deps[:5]:
        count = len(depends_on[f])
        if count > 0:
            bar = "█" * min(count, 20)
            hub_lines.append(f"    {CYAN}{bar}{RESET} {f} ({count})")

    hub_lines.append("")
    hub_lines.append(f"  {BOLD}Most dependents (imported the most):{RESET}")
    for f in most_dependents[:5]:
        count = len(depended_by[f])
        if count > 0:
            bar = "█" * min(count, 20)
            hub_lines.append(f"    {MAGENTA}{bar}{RESET} {f} ({count})")

    if any(len(depends_on[f]) > 0 for f in most_deps[:5]) or \
       any(len(depended_by[f]) > 0 for f in most_dependents[:5]):
        box("Hub Files (highest risk to change)", hub_lines, YELLOW)

    # ── Isolated files ──────────────────────────────────────────────────
    if isolated:
        iso_lines = [f"  {DIM}{f}{RESET}" for f in isolated[:20]]
        if len(isolated) > 20:
            iso_lines.append(f"  {DIM}... and {len(isolated) - 20} more{RESET}")
        box("Isolated Files (no imports detected)", iso_lines, DIM + CYAN)

    # ── Export ──────────────────────────────────────────────────────────
    if export_json:
        graph_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "files": len(files),
            "edges": total_edges,
            "depends_on": {f: deps for f, deps in depends_on.items() if deps},
            "depended_by": {f: deps for f, deps in depended_by.items() if deps},
            "isolated": isolated,
        }
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(GRAPH_JSON, "w", encoding="utf-8") as fh:
            json.dump(graph_data, fh, indent=2)
        print(f"\n  {GREEN}✔{RESET} Exported to {os.path.relpath(GRAPH_JSON)}")

    # ── Visual graph ───────────────────────────────────────────────────
    if visual:
        generate_visual_graph(files, depends_on, depended_by)

    print()


def cmd_impact(target_file):
    """Show the blast radius of changing a specific file."""
    # normalize input
    target_file = target_file.replace("\\", "/")

    header(f"Impact Analysis: {target_file}", "\U0001f4a5")

    config = load_config()
    patterns = config.get("watch_patterns", [])
    files = collect_project_files(patterns)

    if target_file not in files:
        # try fuzzy match
        matches = [f for f in files if target_file in f]
        if len(matches) == 1:
            target_file = matches[0]
            print(f"  {DIM}Matched: {target_file}{RESET}")
        elif len(matches) > 1:
            print(f"  {YELLOW}Ambiguous — multiple matches:{RESET}")
            for m in matches:
                print(f"    {m}")
            print(f"\n  {YELLOW}Be more specific.{RESET}")
            print()
            return
        else:
            print(f"  {RED}File not found in watched files: {target_file}{RESET}")
            print(f"  {DIM}Run --graph to see all tracked files.{RESET}")
            print()
            return

    depends_on, depended_by = build_dependency_graph(files)

    # ── What this file imports ──────────────────────────────────────────
    direct_deps = depends_on.get(target_file, [])
    if direct_deps:
        dep_lines = [f"  {GREEN}{d}{RESET}" for d in direct_deps]
        box(f"{target_file} depends on", dep_lines, GREEN)

    # ── Direct dependents ───────────────────────────────────────────────
    direct_dependents = depended_by.get(target_file, [])

    # ── Full impact chain (BFS) ─────────────────────────────────────────
    impact = get_impact_chain(target_file, depended_by)
    # remove self
    impact.pop(target_file, None)

    if impact:
        # ── Visual tree ─────────────────────────────────────────────────
        print(f"\n  {BOLD}Impact tree:{RESET}")
        print(f"  {RED}{target_file}{RESET}  ← you change this")
        print_tree(target_file, depended_by, prefix="  ")

        # ── Blast radius summary ────────────────────────────────────────
        by_depth = collections.defaultdict(list)
        for f, d in impact.items():
            by_depth[d].append(f)

        radius_lines = []
        for depth in sorted(by_depth.keys()):
            label = "direct" if depth == 1 else f"depth {depth}"
            flist = by_depth[depth]
            color = RED if depth == 1 else YELLOW if depth == 2 else DIM
            radius_lines.append(f"  {color}Level {depth} ({label}):{RESET}")
            for f in flist:
                radius_lines.append(f"    {color}→ {f}{RESET}")
        radius_lines.append("")
        radius_lines.append(f"  Total files affected: {BOLD}{len(impact)}{RESET}")

        risk = "LOW" if len(impact) <= 2 else "MEDIUM" if len(impact) <= 5 else "HIGH"
        risk_color = GREEN if risk == "LOW" else YELLOW if risk == "MEDIUM" else RED
        radius_lines.append(f"  Risk level: {risk_color}{BOLD}{risk}{RESET}")

        box("Blast Radius", radius_lines, RED)
    else:
        lines = [
            f"  No other files depend on {BOLD}{target_file}{RESET}.",
            f"  Changing it affects {GREEN}only itself{RESET}.",
            "",
            f"  Risk level: {GREEN}{BOLD}LOW{RESET}",
        ]
        box("Blast Radius", lines, GREEN)

    # ── Recommendation ──────────────────────────────────────────────────
    if len(impact) > 5:
        print(f"  {YELLOW}⚠  This is a high-impact file. Test thoroughly.{RESET}")
        print(f"  {YELLOW}   Consider running --pre before making changes.{RESET}")
    elif direct_dependents:
        print(f"  {CYAN}ℹ  {len(direct_dependents)} file(s) directly use this. Review them after changes.{RESET}")
    else:
        print(f"  {GREEN}✔  Safe to change in isolation.{RESET}")
    print()


def cmd_history():
    """Display fix history."""
    header("Fix History", "\U0001f4dc")

    history = load_history()
    fixes = history.get("fixes", [])

    if not fixes:
        print(f"  {DIM}No fixes recorded yet.{RESET}")
        print(f"  {DIM}History is recorded automatically after each --compare.{RESET}")
        print()
        return

    # ── Stats ───────────────────────────────────────────────────────────
    total = len(fixes)
    passed = sum(1 for f in fixes if f["result"] == "PASSED")
    failed_reg = sum(1 for f in fixes if f["result"] == "FAILED_REGRESSION")
    failed_no_imp = sum(1 for f in fixes if f["result"] == "FAILED_NO_IMPROVEMENT")
    total_improvements = sum(len(f.get("improvements", [])) for f in fixes)
    total_regressions = sum(len(f.get("regressions", [])) for f in fixes)
    total_files_changed = sum(
        len(f.get("files_modified", [])) + len(f.get("files_added", [])) + len(f.get("files_removed", []))
        for f in fixes
    )

    stat_lines = [
        f"Total fix cycles: {BOLD}{total}{RESET}",
        f"Passed: {GREEN}{BOLD}{passed}{RESET}",
        f"Failed (regression): {RED}{BOLD}{failed_reg}{RESET}",
        f"Failed (no improvement): {YELLOW}{BOLD}{failed_no_imp}{RESET}",
        f"Total checks improved: {GREEN}{total_improvements}{RESET}",
        f"Total regressions caught: {RED}{total_regressions}{RESET}",
        f"Total files changed: {BOLD}{total_files_changed}{RESET}",
    ]

    if passed > 0 and total > 0:
        rate = (passed / total) * 100
        color = GREEN if rate >= 80 else YELLOW if rate >= 50 else RED
        stat_lines.append(f"Success rate: {color}{BOLD}{rate:.0f}%{RESET}")

    box("Overview", stat_lines)

    # ── Timeline ────────────────────────────────────────────────────────
    timeline_lines = []
    for fix in reversed(fixes[-20:]):
        fid = fix["id"]
        ts = fix["timestamp"][:19].replace("T", " ")
        result = fix["result"]
        imps = fix.get("improvements", [])
        regs = fix.get("regressions", [])
        mods = len(fix.get("files_modified", []))
        adds = len(fix.get("files_added", []))
        rems = len(fix.get("files_removed", []))
        file_count = mods + adds + rems

        if result == "PASSED":
            icon = f"{GREEN}✔{RESET}"
            label = f"{GREEN}PASSED{RESET}"
        elif result == "FAILED_REGRESSION":
            icon = f"{RED}✘{RESET}"
            label = f"{RED}REGRESSION{RESET}"
        else:
            icon = f"{YELLOW}○{RESET}"
            label = f"{YELLOW}NO IMPROVEMENT{RESET}"

        detail_parts = []
        if imps:
            detail_parts.append(f"{GREEN}+{len(imps)} improved{RESET}")
        if regs:
            detail_parts.append(f"{RED}-{len(regs)} regressed{RESET}")
        if file_count:
            detail_parts.append(f"{DIM}{file_count} files{RESET}")
        detail = "  ".join(detail_parts)

        timeline_lines.append(f"  {icon} {DIM}#{fid}{RESET}  {DIM}{ts}{RESET}  {label}  {detail}")

    if len(fixes) > 20:
        timeline_lines.append(f"  {DIM}... and {len(fixes) - 20} earlier fixes{RESET}")

    box("Timeline (newest first)", timeline_lines)

    # ── Streak ──────────────────────────────────────────────────────────
    current_streak = 0
    for fix in reversed(fixes):
        if fix["result"] == "PASSED":
            current_streak += 1
        else:
            break

    best_streak = 0
    streak = 0
    for fix in fixes:
        if fix["result"] == "PASSED":
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

    if total >= 3:
        streak_lines = [
            f"  Current streak: {GREEN}{BOLD}{current_streak}{RESET} clean fix(es) in a row",
            f"  Best streak: {CYAN}{BOLD}{best_streak}{RESET} clean fix(es)",
        ]
        if current_streak >= 5:
            streak_lines.append(f"  {GREEN}On fire — {current_streak} fixes with zero regressions!{RESET}")
        box("Streaks", streak_lines, GREEN if current_streak > 0 else YELLOW)

    # ── Files most frequently changed ───────────────────────────────────
    file_freq = collections.Counter()
    for fix in fixes:
        for f in fix.get("files_modified", []):
            file_freq[f] += 1
        for f in fix.get("files_added", []):
            file_freq[f] += 1

    if file_freq:
        top_files = file_freq.most_common(5)
        freq_lines = []
        for f, count in top_files:
            bar = "█" * min(count, 20)
            freq_lines.append(f"  {YELLOW}{bar}{RESET} {f} ({count}x)")
        box("Most frequently changed files", freq_lines, YELLOW)

    print()


def cmd_scan(severity_filter=None, category_filter=None, export_json=False):
    """Scan the entire codebase for bugs, vulnerabilities, and code quality issues."""
    header("Scanning Codebase", "\U0001f50e")

    config = load_config()
    patterns = config.get("watch_patterns", [])
    files = collect_project_files(patterns)

    if not files:
        print(f"  {YELLOW}No files found matching watch_patterns.{RESET}")
        print(f"  {DIM}Run --init --auto to configure.{RESET}")
        print()
        return

    # detect languages present
    languages = set()
    file_langs = {}
    for f in files:
        lang = detect_language(f)
        if lang:
            languages.add(lang)
            file_langs[f] = lang

    print(f"  Scanning {BOLD}{len(files)}{RESET} files across {BOLD}{len(languages)}{RESET} language(s)...")
    print(f"  Languages: {', '.join(sorted(languages))}")
    print()

    # built-in scan
    all_findings = []
    scanned = 0
    for f, lang in file_langs.items():
        findings = scan_file(f, lang)
        all_findings.extend(findings)
        scanned += 1

    print(f"  {GREEN}✔{RESET} Built-in rules: scanned {scanned} files, found {BOLD}{len(all_findings)}{RESET} issues")

    # external scanners
    ext_findings = run_external_scanners(languages)
    if ext_findings:
        print(f"  {GREEN}✔{RESET} External tools: found {BOLD}{len(ext_findings)}{RESET} additional issues")
        all_findings.extend(ext_findings)

    # deduplicate
    all_findings = deduplicate_findings(all_findings)

    # filter
    if severity_filter:
        sev_set = {s.upper() for s in severity_filter.split(",")}
        all_findings = [f for f in all_findings if f["severity"] in sev_set]
    if category_filter:
        cat_set = {c.lower() for c in category_filter.split(",")}
        all_findings = [f for f in all_findings if f["category"] in cat_set]

    # sort by severity
    all_findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 99), f["file"], f["line"]))

    if not all_findings:
        box("Scan Results", [
            f"  {GREEN}{BOLD}No issues found!{RESET}",
            f"  {DIM}Your codebase looks clean.{RESET}",
        ], GREEN)
        print()
        return

    # count by severity and category
    sev_counts = collections.Counter(f["severity"] for f in all_findings)
    cat_counts = collections.Counter(f["category"] for f in all_findings)

    summary_lines = [
        f"  Total issues: {BOLD}{len(all_findings)}{RESET}",
        "",
        f"  {BOLD}By severity:{RESET}",
    ]
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = sev_counts.get(sev, 0)
        if count == 0:
            continue
        color = RED if sev == "CRITICAL" else RED if sev == "HIGH" else YELLOW if sev == "MEDIUM" else DIM
        bar = "█" * min(count, 30)
        summary_lines.append(f"    {color}{bar}{RESET} {sev}: {BOLD}{count}{RESET}")

    summary_lines.append("")
    summary_lines.append(f"  {BOLD}By category:{RESET}")
    for cat in ["security", "logic", "quality"]:
        count = cat_counts.get(cat, 0)
        if count > 0:
            icon = "\U0001f6e1️" if cat == "security" else "\U0001f9e9" if cat == "logic" else "✨"
            summary_lines.append(f"    {icon}  {cat}: {BOLD}{count}{RESET}")

    box("Scan Summary", summary_lines, RED if sev_counts.get("CRITICAL", 0) > 0 else YELLOW)

    # group findings by file
    by_file = collections.defaultdict(list)
    for f in all_findings:
        by_file[f["file"]].append(f)

    for filepath in sorted(by_file.keys()):
        file_findings = by_file[filepath]
        finding_lines = []
        for f in file_findings:
            sev = f["severity"]
            color = RED if sev in ("CRITICAL", "HIGH") else YELLOW if sev == "MEDIUM" else DIM
            icon = "\U0001f6a8" if sev == "CRITICAL" else "⚠️" if sev == "HIGH" else "○" if sev == "MEDIUM" else "·"
            finding_lines.append(f"  {color}{icon} Line {f['line']}: {BOLD}{f['name']}{RESET} [{sev}]")
            finding_lines.append(f"    {DIM}{f['description']}{RESET}")
            if f["line_text"]:
                text = f["line_text"][:100]
                finding_lines.append(f"    {DIM}> {text}{RESET}")
            finding_lines.append(f"    {CYAN}Fix: {f['fix']}{RESET}")
            finding_lines.append("")

        file_color = RED if any(f["severity"] in ("CRITICAL", "HIGH") for f in file_findings) else YELLOW
        box(f"{filepath} ({len(file_findings)} issues)", finding_lines, file_color)

    # save report
    report_path = _resolve_scan_report_path()
    os.makedirs(CACHE_DIR, exist_ok=True)
    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "files_scanned": scanned,
        "total_issues": len(all_findings),
        "by_severity": dict(sev_counts),
        "by_category": dict(cat_counts),
        "findings": all_findings,
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\n  {GREEN}✔{RESET} Report saved to {os.path.relpath(report_path)}")

    # final verdict
    if sev_counts.get("CRITICAL", 0) > 0:
        print(f"\n  {RED}{BOLD}\U0001f6a8 {sev_counts['CRITICAL']} CRITICAL issue(s) found — fix these first.{RESET}")
    elif sev_counts.get("HIGH", 0) > 0:
        print(f"\n  {YELLOW}{BOLD}⚠️  {sev_counts['HIGH']} HIGH severity issue(s) found.{RESET}")
    else:
        print(f"\n  {YELLOW}Only medium/low issues remain.{RESET}")

    print()


def cmd_reset():
    """Delete cached state files."""
    header("Resetting cache", "\U0001f9f9")
    scan_report = _resolve_scan_report_path()
    targets = [PRE_STATE, POST_STATE, ANALYSIS_MD, FIX_PLAN_MD, GRAPH_JSON, HISTORY_JSON, scan_report]
    for path in targets:
        if os.path.exists(path):
            os.remove(path)
            print(f"  {GREEN}✔{RESET} Deleted {os.path.basename(path)}")
        else:
            print(f"  {DIM}– {os.path.basename(path)} not found, skipping{RESET}")
    print()


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Safe Fix Verifier — capture and compare project state around fixes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="Initialize config, cache dir, and .gitignore")
    group.add_argument("--pre", action="store_true", help="Capture pre-fix state")
    group.add_argument("--post", action="store_true", help="Capture post-fix state")
    group.add_argument("--compare", action="store_true", help="Compare pre and post states")
    group.add_argument("--graph", action="store_true", help="Build and display the dependency graph")
    group.add_argument("--impact", metavar="FILE", help="Show blast radius of changing a file")
    group.add_argument("--history", action="store_true", help="Show fix history and stats")
    group.add_argument("--scan", action="store_true", help="Scan codebase for bugs, vulnerabilities, and code quality issues")
    group.add_argument("--reset", action="store_true", help="Delete cached state files")

    parser.add_argument("--auto", action="store_true", help="Auto-detect project stack (use with --init)")
    parser.add_argument("--json", action="store_true", help="Export graph data to JSON (use with --graph)")
    parser.add_argument("--visual", action="store_true", help="Generate interactive HTML graph and open in browser (use with --graph)")
    parser.add_argument("--project", metavar="DIR", help="Target project directory (default: parent of .safe-fix/)")
    parser.add_argument("--severity", metavar="LEVELS", help="Filter scan by severity: CRITICAL,HIGH,MEDIUM,LOW")
    parser.add_argument("--category", metavar="TYPES", help="Filter scan by category: security,logic,quality")

    args = parser.parse_args()

    if args.project:
        target = os.path.abspath(args.project)
        if not os.path.isdir(target):
            print(f"{RED}  --project path does not exist: {target}{RESET}")
            sys.exit(1)
        set_project_root(target)

    if args.init:
        cmd_init(auto=args.auto)
    elif args.pre:
        cmd_pre()
    elif args.post:
        cmd_post()
    elif args.compare:
        cmd_compare()
    elif args.graph:
        cmd_graph(export_json=args.json, visual=args.visual)
    elif args.impact:
        cmd_impact(args.impact)
    elif args.history:
        cmd_history()
    elif args.scan:
        cmd_scan(severity_filter=args.severity, category_filter=args.category, export_json=args.json)
    elif args.reset:
        cmd_reset()


if __name__ == "__main__":
    main()
