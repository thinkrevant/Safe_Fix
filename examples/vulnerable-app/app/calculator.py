"""Basic calculator module."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    # BUG: no zero-division guard
    return a / b


def average(numbers):
    # BUG: crashes on empty list (ZeroDivisionError)
    return sum(numbers) / len(numbers)


def percentage(value, total):
    # BUG: no zero guard, and wrong formula (should be value/total * 100)
    return total / value * 100


def power(base, exp):
    # BUG: doesn't handle negative exponents correctly for integers
    result = 1
    for _ in range(exp):
        result *= base
    return result
