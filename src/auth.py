"""App passwords for the local Streamlit app.

Two passwords, two views (not user accounts):
    staff password     -> simple menu: add, check, Excel, ask a question
    developer password -> everything, including analytics and setup pages

We store only salted hashes in .env, never the passwords themselves.
Format: pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
"""

STAFF = "staff"
DEVELOPER = "developer"

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000      # slow on purpose, so guessing passwords is expensive


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"{ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password, stored_hash):
    """True if password matches the stored hash. False for any bad input."""
    if not password or not stored_hash:
        return False
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False
        candidate = hash_password(password, salt=salt, iterations=int(iterations))
    except ValueError:
        return False
    # compare_digest takes the same time whether or not the start matches
    return hmac.compare_digest(candidate, stored_hash)


def role_for_password(password, staff_hash, developer_hash):
    """Which view this password opens: DEVELOPER, STAFF, or None (wrong password)."""
    if verify_password(password, developer_hash):
        return DEVELOPER
    if verify_password(password, staff_hash):
        return STAFF
    return None
