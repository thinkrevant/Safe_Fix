"""Input sanitization module — has gaps for testing."""

import re


def sanitize_html(text):
    # BUG: incomplete — only strips <script> but not event handlers or other tags
    return re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL)


def sanitize_email(email):
    # BUG: overly permissive regex
    pattern = r".+@.+"
    if re.match(pattern, email):
        return email
    raise ValueError(f"Invalid email: {email}")


def sanitize_filename(filename):
    # BUG: doesn't handle .. or absolute paths
    return filename.replace(" ", "_")


def sanitize_int(value):
    # BUG: doesn't handle negative numbers or overflow
    return int(value)


def truncate(text, max_length=100):
    # BUG: off-by-one, returns max_length+3 chars when truncating
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def slugify(text):
    # BUG: doesn't handle unicode, consecutive hyphens, or leading/trailing hyphens
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text
