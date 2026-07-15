import os
import tempfile

from django.test import TestCase

from api.services.llm import validate_regex
from api.services.read_columns import read_columns


class ValidateRegexTests(TestCase):
    def test_accepts_simple_pattern(self):
        self.assertEqual(validate_regex(r"\d+"), r"\d+")

    def test_rejects_invalid_syntax(self):
        with self.assertRaises(ValueError):
            validate_regex("([")

    def test_rejects_unsafe_nested_quantifiers(self):
        with self.assertRaises(ValueError):
            validate_regex(r"(a+)+$")


class ReadColumnsTests(TestCase):
    def test_reads_csv_header(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("name,email,age\n")
            f.write("Alice,alice@example.com,30\n")
            path = f.name

        try:
            self.assertEqual(read_columns(path), ["name", "email", "age"])
        finally:
            os.unlink(path)

    def test_returns_empty_for_blank_csv(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("\n")
            path = f.name

        try:
            self.assertEqual(read_columns(path), [])
        finally:
            os.unlink(path)
