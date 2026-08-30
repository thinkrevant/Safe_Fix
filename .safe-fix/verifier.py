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
import os
import re
import subprocess
import sys

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Paths ───────────────────────────────────────────────────────────────────

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


def cmd_graph(export_json=False):
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


def cmd_reset():
    """Delete cached state files."""
    header("Resetting cache", "\U0001f9f9")
    targets = [PRE_STATE, POST_STATE, ANALYSIS_MD, FIX_PLAN_MD, GRAPH_JSON, HISTORY_JSON]
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
    group.add_argument("--reset", action="store_true", help="Delete cached state files")

    parser.add_argument("--auto", action="store_true", help="Auto-detect project stack (use with --init)")
    parser.add_argument("--json", action="store_true", help="Export graph data to JSON (use with --graph)")

    args = parser.parse_args()

    if args.init:
        cmd_init(auto=args.auto)
    elif args.pre:
        cmd_pre()
    elif args.post:
        cmd_post()
    elif args.compare:
        cmd_compare()
    elif args.graph:
        cmd_graph(export_json=args.json)
    elif args.impact:
        cmd_impact(args.impact)
    elif args.history:
        cmd_history()
    elif args.reset:
        cmd_reset()


if __name__ == "__main__":
    main()
