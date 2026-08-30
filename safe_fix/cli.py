#!/usr/bin/env python3
"""Entry point for `safe-fix` CLI command."""

import os
import shutil
import subprocess
import sys


def _find_verifier():
    """Find verifier.py — bundled in package or in target project."""
    return os.path.join(os.path.dirname(__file__), "verifier.py")


def main():
    argv = sys.argv[1:]

    # Extract --project value from args, default to CWD
    project_dir = None
    i = 0
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            project_dir = argv[i + 1]
            break
        if argv[i].startswith("--project="):
            project_dir = argv[i].split("=", 1)[1]
            break
        i += 1

    if project_dir is None:
        project_dir = os.getcwd()
        argv.extend(["--project", project_dir])

    # For --init: copy verifier.py into target project's .safe-fix/
    is_init = "--init" in argv
    if is_init:
        safe_fix_dir = os.path.join(os.path.abspath(project_dir), ".safe-fix")
        os.makedirs(safe_fix_dir, exist_ok=True)
        bundled = _find_verifier()
        target = os.path.join(safe_fix_dir, "verifier.py")
        if os.path.exists(bundled):
            shutil.copy2(bundled, target)

    verifier = _find_verifier()
    if not os.path.exists(verifier):
        print("Error: verifier.py not found in package.")
        sys.exit(1)

    result = subprocess.run([sys.executable, verifier] + argv)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
