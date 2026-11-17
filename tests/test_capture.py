"""Tests for the capture flow, the app password and the Streamlit pages."""

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
def test_home_without_password_hash_shows_setup_message(monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", None)
    app = AppTest.from_file(str(APP_DIR / "Home.py")).run()
    assert "set_app_password" in app.error[0].value


def test_home_asks_for_password_and_accepts_correct_one(monkeypatch, db_conn):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", auth.hash_password("letmein!", iterations=1000))
    app = AppTest.from_file(str(APP_DIR / "Home.py")).run()
    assert len(app.metric) == 0                    # nothing shown before login

    app.text_input[0].input("wrong-password")
    app.button[0].click().run()
    assert app.error[0].value == "Wrong password."

    app.text_input[0].input("letmein!")
    app.button[0].click().run()
    assert len(app.metric) == 7                    # overview numbers visible after login


def test_add_receipt_page_is_protected(monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD_HASH", auth.hash_password("letmein!", iterations=1000))
    app = AppTest.from_file(str(APP_DIR / "pages" / "1_Add_Receipt.py")).run()
    assert len(app.tabs) == 0                      # capture tabs hidden until login
    assert app.text_input[0].label == "App password"
