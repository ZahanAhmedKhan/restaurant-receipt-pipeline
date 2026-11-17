"""Tests for the capture flow, the app password and the Streamlit pages."""

import pytest
from streamlit.testing.v1 import AppTest

from scripts.set_app_password import update_env_value
from src import auth, config
from src.run_pipeline import process_single_image
from tests.helpers import image_bytes

APP_DIR = config.PROJECT_ROOT / "app"


# --- password hashing --------------------------------------------------------
def test_hash_and_verify_password():
    stored = auth.hash_password("correct horse", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert "correct horse" not in stored
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong", stored)


def test_verify_rejects_bad_input():
    assert not auth.verify_password("", "anything")
    assert not auth.verify_password("x", None)
    assert not auth.verify_password("x", "not-a-hash")


def test_same_password_gets_different_salts():
    assert auth.hash_password("abc", iterations=1000) != auth.hash_password("abc", iterations=1000)


def test_update_env_value_replaces_or_adds():
    assert update_env_value("A=1\nAPP_PASSWORD_HASH=\n", "APP_PASSWORD_HASH", "h") == "A=1\nAPP_PASSWORD_HASH=h\n"
    assert update_env_value("A=1\n", "APP_PASSWORD_HASH", "h") == "A=1\nAPP_PASSWORD_HASH=h\n"


# --- capture flow (test database) ----------------------------------------------
def source_of(conn, file_id):
    return conn.execute("SELECT source FROM raw.receipt_file WHERE file_id = %s",
                        (file_id,)).fetchone()[0]


def test_camera_jpeg_and_uploaded_png_get_right_source(db_conn, tmp_path):
    camera = image_bytes("JPEG", size=(640, 480))          # st.camera_input size
    upload = image_bytes("PNG", size=(1200, 1600), color=(250, 250, 250))

    camera_result = process_single_image(db_conn, camera, "camera.jpg", "camera", raw_dir=tmp_path)
    upload_result = process_single_image(db_conn, upload, "IMG_0001.png", "upload", raw_dir=tmp_path)

    assert camera_result["status"] == "new"
    assert upload_result["status"] == "new"
    assert source_of(db_conn, camera_result["file_id"]) == "camera"
    assert source_of(db_conn, upload_result["file_id"]) == "upload"
    # A blank photo has nothing readable, so it must go to review
    assert camera_result["receipt_id"] is not None
    assert camera_result["needs_review"] is True


def test_real_receipt_then_duplicate(db_conn, tmp_path):
    data = (config.SAMPLE_DIR / "receipt_003.png").read_bytes()
    first = process_single_image(db_conn, data, "r.png", "upload", raw_dir=tmp_path)
    second = process_single_image(db_conn, data, "r.png", "camera", raw_dir=tmp_path)
    assert first["status"] == "new"
    assert second["status"] == "duplicate"
    assert second["receipt_id"] == first["receipt_id"]


def test_rejected_file_reports_reason(db_conn, tmp_path):
    result = process_single_image(db_conn, b"not an image", "x.jpg", "upload", raw_dir=tmp_path)
    assert result == {"status": "rejected", "file_id": None, "receipt_id": None,
                      "reason": "not a valid image", "needs_review": False}


# --- Streamlit pages (password gate) --------------------------------------------
STAFF_HASH = auth.hash_password("staff-pass", iterations=1000)
DEV_HASH = auth.hash_password("developer-pass", iterations=1000)


@pytest.fixture
def two_passwords(monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", STAFF_HASH)
    monkeypatch.setattr(config, "DEVELOPER_PASSWORD_HASH", DEV_HASH)


def test_role_for_password():
    assert auth.role_for_password("staff-pass", STAFF_HASH, DEV_HASH) == auth.STAFF
    assert auth.role_for_password("developer-pass", STAFF_HASH, DEV_HASH) == auth.DEVELOPER
    assert auth.role_for_password("nope", STAFF_HASH, DEV_HASH) is None
    assert auth.role_for_password("staff-pass", STAFF_HASH, None) == auth.STAFF


def test_home_without_password_hash_shows_setup_message(monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", None)
    monkeypatch.setattr(config, "DEVELOPER_PASSWORD_HASH", None)
    app = AppTest.from_file(str(APP_DIR / "Home.py")).run()
    assert "set_app_password" in app.error[0].value


def login(password):
    app = AppTest.from_file(str(APP_DIR / "Home.py"), default_timeout=30).run()
    app.text_input[0].input(password)
    app.button[0].click().run()
    return app


def test_wrong_password_is_refused(two_passwords):
    app = login("wrong-password")
    assert app.error[0].value == "Wrong password."
    assert "role" not in app.session_state


def test_staff_login_opens_simple_start_page(two_passwords, db_conn):
    app = login("staff-pass")
    assert not app.exception
    assert app.session_state["role"] == "staff"
    assert app.title[0].value == "🧾 Receipts"                    # the Start page
    assert "Logged in: Staff" in [c.value for c in app.sidebar.caption]


def test_developer_login(two_passwords, db_conn):
    app = login("developer-pass")
    assert not app.exception
    assert app.session_state["role"] == "developer"


def test_staff_cannot_open_developer_pages(db_conn):
    for page in ["0_Overview.py", "4_Items.py", "5_Spending.py", "6_Prices.py",
                 "7_Suppliers.py", "8_OCR_Evaluation.py"]:
        app = AppTest.from_file(str(APP_DIR / "pages" / page))
        app.session_state["role"] = "staff"
        app.run()
        assert app.error[0].value == "This page is only for the developer account.", page


def test_add_receipt_page_is_protected(two_passwords):
    app = AppTest.from_file(str(APP_DIR / "pages" / "1_Add_Receipt.py")).run()
    assert len(app.tabs) == 0                      # capture tabs hidden until login
    assert app.text_input[0].label == "Password"
