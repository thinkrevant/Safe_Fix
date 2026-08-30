# Safe Fix Protocol

When asked to **fix**, **debug**, **patch**, or **address any vulnerability**, follow every step below in order. Never skip any step. Never say "fixed", "done", or "resolved" until Step 5 exits with code 0.

## Step 1 — SNAPSHOT

Run:

```bash
python .safe-fix/verifier.py --pre
```

If it fails, tell the user to run `--init` first. Do not proceed until this succeeds.

## Step 2 — ANALYZE

Before writing any code:

1. Run `python .safe-fix/verifier.py --impact <file>` on the file you plan to change to see its blast radius.
2. Read every file related to the issue, including all files shown in the impact tree.
3. Search the entire codebase for other instances of the same pattern using `grep` or `find`.
4. Trace all downstream effects.
5. If fixing file A could affect file B, handle both in the same step.
6. Write findings to `.safe-fix/cache/analysis.md`.

## Step 3 — PLAN

Before modifying any file, document:

- Every file you will change and why.
- The root cause — not just the symptom.
- Any new risks the fix could introduce.

Write this to `.safe-fix/cache/fix-plan.md`.

## Step 4 — IMPLEMENT

Apply every change in your plan. Do not stop halfway. Do not ask for mid-fix confirmation.

## Step 5 — VERIFY

Run:

```bash
python .safe-fix/verifier.py --post
python .safe-fix/verifier.py --compare
```

If `--compare` exits 1:

- Do **not** say "fixed" or "done".
- Return to Step 2 using the new failure as input.
- Fix the regression, then re-run Step 5.
- After **3 failed retries**, stop and explain the situation to the user.

## Step 6 — SIGN OFF

Only say **"Fix complete"** when `--compare` exits 0. Include:

- What was fixed.
- Root cause.
- Every file changed.
- The full verification output.

---

## Hard Rules

- **Never** skip Step 1, even for a one-line fix.
- **Never** skip Step 5, even if you are certain nothing broke.
- **Never** say "fixed" or "done" before exit code 0.
- If Step 5 fails 3 times, **pause and explain** to the user.
