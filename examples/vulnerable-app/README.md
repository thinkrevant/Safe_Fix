# Vulnerable App — Safe Fix Demo

A small Python project with **15 intentional bugs and vulnerabilities** for testing the Safe Fix system.

## Vulnerabilities included

| File | Issues |
|------|--------|
| `app/calculator.py` | Division by zero, empty list crash, wrong formula, negative exponent bug |
| `app/user_manager.py` | SQL injection (5 functions), hardcoded secrets, MD5 password hashing |
| `app/file_handler.py` | Path traversal, command injection, pickle deserialization, insecure temp file |
| `app/sanitizer.py` | Incomplete HTML sanitization, weak email regex, missing path checks, off-by-one, bad slugify |

## Setup

```bash
cd examples/vulnerable-app

# Copy the safe-fix system into this directory
cp -r ../../.safe-fix .
cp config.json .safe-fix/config.json

# Install test runner
pip install pytest

# Run the tests to see the failures
python -m pytest tests/ -q
```

## Try it

Try fixing any of the vulnerabilities and watch the 6-step protocol run.

Example prompts:
- "Fix the SQL injection in user_manager.py"
- "Fix the path traversal vulnerability in file_handler.py"
- "Fix the calculator bugs"
