Triggered when the user asks to fix, debug, patch, or address a vulnerability.

Run `python .safe-fix/verifier.py --pre` then analyze the full codebase and write findings to `.safe-fix/cache/analysis.md` then plan every file change and write to `.safe-fix/cache/fix-plan.md` then apply all changes atomically then run `python .safe-fix/verifier.py --post` then run `python .safe-fix/verifier.py --compare`.

If exit code is 0 say **Fix complete** with full summary. If exit code is 1 re-analyze the regression, fix it, and re-run. After 3 retries stop and explain.

**Never say "fixed", "done", or "resolved" before exit code 0.**

Sign-off format:

> **Fix complete.**
> **Problem:** root cause.
> **Changed:** every file.
> **Verified:** paste the compare output.
