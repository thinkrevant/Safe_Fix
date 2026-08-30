"""File handling module — deliberately vulnerable for testing."""

import os
import pickle
import subprocess
import tempfile


UPLOAD_DIR = "uploads"


def read_file(filename):
    # VULNERABILITY: path traversal — no sanitization
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "r") as f:
        return f.read()


def write_file(filename, content):
    # VULNERABILITY: path traversal — no sanitization
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "w") as f:
        f.write(content)


def delete_file(filename):
    # VULNERABILITY: path traversal + no existence check
    path = os.path.join(UPLOAD_DIR, filename)
    os.remove(path)


def run_command(user_input):
    # VULNERABILITY: command injection via shell=True with user input
    result = subprocess.run(
        f"echo Processing: {user_input}",
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def process_data(data_bytes):
    # VULNERABILITY: deserializing untrusted data with pickle
    return pickle.loads(data_bytes)


def make_temp_file(content):
    # VULNERABILITY: insecure temp file creation (predictable name)
    path = os.path.join(tempfile.gettempdir(), "app_temp_data.txt")
    with open(path, "w") as f:
        f.write(content)
    return path


def download_to(url, dest_dir, filename):
    # VULNERABILITY: command injection via filename in shell command
    cmd = f"curl -o {dest_dir}/{filename} {url}"
    os.system(cmd)
