"""Tests for sanitizer module."""

import unittest
from app.sanitizer import (
    sanitize_html, sanitize_email, sanitize_filename,
    sanitize_int, truncate, slugify,
)


class TestSanitizeHtml(unittest.TestCase):
    def test_strips_script(self):
        result = sanitize_html("hello <script>alert('xss')</script> world")
        self.assertNotIn("<script", result)

    def test_strips_event_handlers(self):
        # This CATCHES the bug — onerror is not stripped
        result = sanitize_html('<img src=x onerror="alert(1)">')
        self.assertNotIn("onerror", result)

    def test_strips_iframe(self):
        # This CATCHES the bug — iframe is not stripped
        result = sanitize_html('<iframe src="evil.com"></iframe>')
        self.assertNotIn("<iframe", result)

    def test_safe_text_unchanged(self):
        self.assertEqual(sanitize_html("hello world"), "hello world")


class TestSanitizeEmail(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sanitize_email("user@example.com"), "user@example.com")

    def test_invalid_no_at(self):
        with self.assertRaises(ValueError):
            sanitize_email("not-an-email")

    def test_rejects_spaces(self):
        # This CATCHES the bug — spaces should be rejected
        with self.assertRaises(ValueError):
            sanitize_email("user @example.com")

    def test_rejects_double_at(self):
        # This CATCHES the bug — double @ should be rejected
        with self.assertRaises(ValueError):
            sanitize_email("user@@example.com")


class TestSanitizeFilename(unittest.TestCase):
    def test_spaces_replaced(self):
        self.assertEqual(sanitize_filename("my file.txt"), "my_file.txt")

    def test_blocks_traversal(self):
        # This CATCHES the bug — ../etc/passwd should be blocked
        with self.assertRaises(ValueError):
            sanitize_filename("../../etc/passwd")

    def test_blocks_absolute(self):
        # This CATCHES the bug — absolute paths should be blocked
        with self.assertRaises(ValueError):
            sanitize_filename("/etc/passwd")


class TestSanitizeInt(unittest.TestCase):
    def test_string_number(self):
        self.assertEqual(sanitize_int("42"), 42)

    def test_rejects_non_numeric(self):
        with self.assertRaises(ValueError):
            sanitize_int("abc")


class TestTruncate(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(truncate("hi", 10), "hi")

    def test_exact_length(self):
        text = "a" * 10
        self.assertEqual(truncate(text, 10), text)

    def test_long_truncated(self):
        text = "a" * 20
        result = truncate(text, 10)
        # Total length should be max_length, not max_length + 3
        self.assertLessEqual(len(result), 10, "Truncated result should not exceed max_length")


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_special_chars(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world-")

    def test_no_leading_trailing_hyphens(self):
        # This CATCHES the bug — leading/trailing hyphens should be stripped
        result = slugify("--hello--")
        self.assertFalse(result.startswith("-"), "Should not start with hyphen")
        self.assertFalse(result.endswith("-"), "Should not end with hyphen")

    def test_no_consecutive_hyphens(self):
        # This CATCHES the bug — consecutive hyphens should collapse
        result = slugify("hello    world")
        self.assertNotIn("--", result)


if __name__ == "__main__":
    unittest.main()
