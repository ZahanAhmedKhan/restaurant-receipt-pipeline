"""Set the Streamlit app password.

Asks for a new password (twice), hashes it, and writes APP_PASSWORD_HASH
into .env. The password itself is never saved.

Usage:
    python scripts/set_app_password.py
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth import hash_password  # noqa: E402

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
MIN_LENGTH = 8


def update_env_value(env_text, key, value):
    """Replace KEY=... in the .env text, or add it at the end."""
    lines = env_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            return "\n".join(lines) + "\n"
    lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main():
    password = getpass.getpass("New app password: ")
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.")
        sys.exit(1)
    if getpass.getpass("Repeat it: ") != password:
        print("The two passwords don't match.")
        sys.exit(1)

    env_text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    ENV_FILE.write_text(update_env_value(env_text, "APP_PASSWORD_HASH", hash_password(password)),
                        encoding="utf-8")
    print("App password saved (as a hash) in .env. Restart Streamlit to use it.")


if __name__ == "__main__":
    main()
