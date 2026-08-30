"""Tests for calculator module."""

import unittest
from app.calculator import add, subtract, multiply, divide, average, percentage, power


class TestAdd(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-1, -1), -2)

    def test_mixed(self):
        self.assertEqual(add(-1, 1), 0)

    def test_floats(self):
        self.assertAlmostEqual(add(0.1, 0.2), 0.3)


class TestSubtract(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_result_negative(self):
        self.assertEqual(subtract(3, 5), -2)


class TestMultiply(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(multiply(3, 4), 12)

    def test_zero(self):
        self.assertEqual(multiply(5, 0), 0)


class TestDivide(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(divide(10, 2), 5)

    def test_float_result(self):
        self.assertAlmostEqual(divide(1, 3), 0.3333, places=3)

    def test_divide_by_zero(self):
        # This test CATCHES the bug — divide(1, 0) should raise ValueError, not ZeroDivisionError
        with self.assertRaises(ValueError):
            divide(1, 0)


class TestAverage(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(average([1, 2, 3]), 2.0)

    def test_empty_list(self):
        # This test CATCHES the bug — average([]) should raise ValueError, not ZeroDivisionError
        with self.assertRaises(ValueError):
            average([])

    def test_single(self):
        self.assertEqual(average([5]), 5.0)


class TestPercentage(unittest.TestCase):
    def test_half(self):
        # percentage(50, 100) should return 50.0, not 200.0
        self.assertEqual(percentage(50, 100), 50.0)

    def test_full(self):
        self.assertEqual(percentage(100, 100), 100.0)

    def test_zero_total(self):
        with self.assertRaises(ValueError):
            percentage(50, 0)


class TestPower(unittest.TestCase):
    def test_square(self):
        self.assertEqual(power(3, 2), 9)

    def test_zero_exp(self):
        self.assertEqual(power(5, 0), 1)

    def test_negative_exp(self):
        # power(2, -1) should return 0.5 — this catches the negative exponent bug
        self.assertAlmostEqual(power(2, -1), 0.5)


if __name__ == "__main__":
    unittest.main()
