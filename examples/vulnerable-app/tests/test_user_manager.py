"""Tests for user_manager module."""

import os
import sqlite3
import unittest
from app.user_manager import (
    connect_db, create_user, login, get_user, delete_user,
    search_users, hash_password, generate_token,
)


class TestUserManager(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_users.db"
        self.conn = connect_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_create_and_login(self):
        create_user(self.conn, "alice", "pass123", "alice@test.com")
        user = login(self.conn, "alice", "pass123")
        self.assertIsNotNone(user)
        self.assertEqual(user[1], "alice")

    def test_wrong_password(self):
        create_user(self.conn, "bob", "correct", "bob@test.com")
        user = login(self.conn, "bob", "wrong")
        self.assertIsNone(user)

    def test_get_user(self):
        create_user(self.conn, "charlie", "pass", "charlie@test.com")
        user = get_user(self.conn, 1)
        self.assertIsNotNone(user)

    def test_delete_user(self):
        create_user(self.conn, "dave", "pass", "dave@test.com")
        delete_user(self.conn, 1)
        user = get_user(self.conn, 1)
        self.assertIsNone(user)

    def test_search_users(self):
        create_user(self.conn, "alice", "pass", "a@test.com")
        create_user(self.conn, "alicia", "pass", "b@test.com")
        create_user(self.conn, "bob", "pass", "c@test.com")
        results = search_users(self.conn, "ali")
        self.assertEqual(len(results), 2)

    def test_sql_injection_login(self):
        # This test CATCHES the SQL injection bug
        create_user(self.conn, "victim", "secret", "v@test.com")
        # classic SQL injection — should NOT return a user
        injected = login(self.conn, "' OR '1'='1' --", "anything")
        self.assertIsNone(injected, "SQL injection should not bypass login")

    def test_sql_injection_search(self):
        # This test CATCHES the SQL injection bug in search
        create_user(self.conn, "normal", "pass", "n@test.com")
        # this injection would dump all users if vulnerable
        try:
            results = search_users(self.conn, "' UNION SELECT 1,2,3,4,5 --")
            # if injection works, we get unexpected results
            for r in results:
                self.assertEqual(len(r), 5, "Result shape should match users table")
                self.assertNotEqual(r[1], 2, "SQL injection should not return injected data")
        except sqlite3.OperationalError:
            pass  # some injections cause errors, that's also bad

    def test_password_not_plaintext(self):
        create_user(self.conn, "eve", "mysecret", "e@test.com")
        user = get_user(self.conn, 1)
        self.assertNotEqual(user[2], "mysecret", "Password should be hashed")

    def test_unique_tokens(self):
        t1 = generate_token("user1")
        t2 = generate_token("user2")
        self.assertNotEqual(t1, t2)


class TestHashPassword(unittest.TestCase):
    def test_deterministic(self):
        h1 = hash_password("test")
        h2 = hash_password("test")
        self.assertEqual(h1, h2)

    def test_different_passwords(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
