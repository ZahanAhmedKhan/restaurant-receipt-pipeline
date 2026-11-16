"""App password hashing (one shared password for the local Streamlit app).

We store only a salted hash in .env, never the password itself.
Format: pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
"""

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
