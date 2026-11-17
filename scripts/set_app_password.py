"""Set one of the two Streamlit app passwords.

    python scripts/set_app_password.py               # staff password (simple menu)
    python scripts/set_app_password.py --developer   # developer password (everything)

Asks for the new password (twice), hashes it, and writes the hash into .env
(APP_PASSWORD_HASH or DEVELOPER_PASSWORD_HASH). The password itself is never saved.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.auth import hash_password, verify_password  # noqa: E402

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
    parser = argparse.ArgumentParser(description="Set an app password.")
    parser.add_argument("--developer", action="store_true",
                        help="set the developer password instead of the staff password")
    args = parser.parse_args()

    if args.developer:
        key, label, other_hash = "DEVELOPER_PASSWORD_HASH", "developer", config.APP_PASSWORD_HASH
    else:
        key, label, other_hash = "APP_PASSWORD_HASH", "staff", config.DEVELOPER_PASSWORD_HASH

    password = getpass.getpass(f"New {label} password: ")
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.")
        sys.exit(1)
    if getpass.getpass("Repeat it: ") != password:
        print("The two passwords don't match.")
        sys.exit(1)
    if verify_password(password, other_hash):
        # Same password for both would always open the developer view
        print("Use a different password from the other account.")
        sys.exit(1)

    env_text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    ENV_FILE.write_text(update_env_value(env_text, key, hash_password(password)), encoding="utf-8")
    print(f"The {label} password is saved (as a hash) in .env. Restart Streamlit to use it.")


if __name__ == "__main__":
    main()
