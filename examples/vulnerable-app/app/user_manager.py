"""User management module — deliberately vulnerable for testing."""

import hashlib
import os
import sqlite3


# VULNERABILITY: hardcoded secret key
SECRET_KEY = "super_secret_key_12345"

# VULNERABILITY: hardcoded database credentials
DB_USER = "admin"
DB_PASS = "password123"


def connect_db(db_path="users.db"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(id INTEGER PRIMARY KEY, username TEXT, password TEXT, email TEXT, role TEXT)"
    )
    return conn


def hash_password(password):
    # VULNERABILITY: using MD5 for password hashing (weak, no salt)
    return hashlib.md5(password.encode()).hexdigest()


def create_user(conn, username, password, email, role="user"):
    # VULNERABILITY: SQL injection via string formatting
    query = f"INSERT INTO users (username, password, email, role) VALUES ('{username}', '{hash_password(password)}', '{email}', '{role}')"
    conn.execute(query)
    conn.commit()


def login(conn, username, password):
    # VULNERABILITY: SQL injection via string formatting
    hashed = hash_password(password)
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{hashed}'"
    cursor = conn.execute(query)
    return cursor.fetchone()


def get_user(conn, user_id):
    # VULNERABILITY: SQL injection via string formatting
    query = f"SELECT * FROM users WHERE id={user_id}"
    cursor = conn.execute(query)
    return cursor.fetchone()


def delete_user(conn, user_id):
    # VULNERABILITY: SQL injection, no authorization check
    query = f"DELETE FROM users WHERE id={user_id}"
    conn.execute(query)
    conn.commit()


def search_users(conn, search_term):
    # VULNERABILITY: SQL injection via string formatting
    query = f"SELECT * FROM users WHERE username LIKE '%{search_term}%'"
    cursor = conn.execute(query)
    return cursor.fetchall()


def change_role(conn, user_id, new_role):
    # VULNERABILITY: no authorization check, SQL injection
    query = f"UPDATE users SET role='{new_role}' WHERE id={user_id}"
    conn.execute(query)
    conn.commit()


def generate_token(username):
    # VULNERABILITY: predictable token using hardcoded secret + MD5
    raw = f"{SECRET_KEY}:{username}"
    return hashlib.md5(raw.encode()).hexdigest()
