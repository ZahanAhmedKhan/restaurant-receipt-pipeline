"""Tests for src/chatbot.py. The Gemini API is never called (it is mocked)."""

import json
from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import chatbot, config, load_mart
from tests.helpers import make_approved_receipt

QUESTIONS = json.loads(chatbot.QUESTIONS_FILE.read_text(encoding="utf-8"))

UNSAFE_SQL = [
    "DELETE FROM mart.fact_purchase_line",
    "DROP TABLE mart.fact_purchase_line",
    "UPDATE mart.dim_item SET item_name = 'x'",
    "INSERT INTO mart.dim_vendor (vendor_name) VALUES ('x')",
    "SELECT * INTO mart.copy FROM mart.dim_vendor",
    "CREATE TABLE mart.x AS SELECT 1",
    "TRUNCATE mart.fact_purchase_line",
    "SELECT raw_text FROM raw.ocr_run",
    "SELECT * FROM clean.receipt",
    "SELECT * FROM pg_catalog.pg_roles",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM dim_vendor",                            # no schema: not allowed
    "SELECT 1 FROM mart.dim_vendor; DROP TABLE mart.dim_vendor",
    "SELECT pg_sleep(10) FROM mart.dim_vendor",
    "SELECT pg_read_file('C:/secret.txt')",
    "SELECT set_config('statement_timeout', '0', false)",
    "COPY mart.dim_vendor TO 'C:/out.csv'",
    "GRANT ALL ON mart.dim_vendor TO public",
    "SET statement_timeout = 0",
    "WITH d AS (DELETE FROM mart.dim_vendor RETURNING *) SELECT * FROM d",
    "this is not sql",
]


# --- validation ------------------------------------------------------------------------
@pytest.mark.parametrize("sql", UNSAFE_SQL)
def test_unsafe_sql_is_blocked(sql):
    with pytest.raises(chatbot.BlockedQuery):
        chatbot.validate_sql(sql)


def test_limit_added_or_lowered():
    assert chatbot.validate_sql("SELECT * FROM mart.dim_item").endswith("LIMIT 200")
    assert chatbot.validate_sql("SELECT * FROM mart.dim_item LIMIT 5").endswith("LIMIT 5")
    assert chatbot.validate_sql("SELECT * FROM mart.dim_item LIMIT 100000").endswith("LIMIT 200")


def test_cte_names_are_allowed():
    sql = "WITH t AS (SELECT vendor_key FROM mart.dim_vendor) SELECT * FROM t"
    assert "FROM t" in chatbot.validate_sql(sql)


def test_extract_sql_removes_markdown_fences():
    assert chatbot.extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert chatbot.extract_sql("  SELECT 2  ") == "SELECT 2"


def test_every_expected_sql_passes_validation():
    for item in QUESTIONS["questions"]:
        chatbot.validate_sql(item["expected_sql"])


def test_question_file_has_25_questions():
    assert len(QUESTIONS["questions"]) == 25


# --- comparing results --------------------------------------------------------------------
def test_results_match_ignores_names_order_and_extra_columns():
    expected = pd.DataFrame({"vendor_name": ["A", "B"]})
    actual = pd.DataFrame({"spend": [10, 20], "v": ["b", "a"]})
    assert chatbot.results_match(expected, actual)
    assert not chatbot.results_match(expected, pd.DataFrame({"v": ["a"]}))
    assert chatbot.results_match(pd.DataFrame({"x": [1.0049]}), pd.DataFrame({"y": [1.0]}))


# --- running (test database) ----------------------------------------------------------------
@pytest.fixture
def mart(db_conn):
    make_approved_receipt(db_conn, 1, "Harbor Fresh Foods", date(2026, 6, 5), [("CHKN BRST 10LB", 2, "CS", "30.00")])
    make_approved_receipt(db_conn, 2, "Harbor Fresh Foods", date(2026, 9, 5), [("CHKN BRST 10LB", 1, "CS", "36.00")])
    make_approved_receipt(db_conn, 3, "Sunrise Meat Co.", date(2026, 9, 6),
                          [("CHICKEN BREAST BNLS 10 LB", 1, "CS", "31.00"), ("GOAT CUBES", 10, "LB", "6.25")])
    load_mart.build_mart(db_conn)
    return db_conn


def test_schema_description_has_structure_only(mart):
    text = chatbot.schema_description(mart)
    assert "mart.fact_purchase_line(" in text
    assert "line_total numeric" in text
    assert "Harbor" not in text                          # no data values


def test_run_readonly_returns_rows(mart):
    result = chatbot.run_readonly("SELECT count(*) AS n FROM mart.fact_purchase_line LIMIT 200")
    assert result["n"].iloc[0] == 4


@pytest.fixture
def fake_gemini(monkeypatch):
    """Gemini that answers SQL questions from a lookup and summarizes results."""
    replies = {}
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        if prompt.startswith("Question:"):
            return "We spent the most with Harbor Fresh Foods."
        for question, sql in replies.items():
            if question in prompt:
                return sql
        return "SELECT 1 FROM mart.dim_vendor"

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(chatbot, "_call_gemini_text", fake)
    return replies, prompts


def test_ask_runs_safe_query_and_answers_on_sample_data(mart, fake_gemini, monkeypatch):
    replies, prompts = fake_gemini
    replies["Which vendor?"] = "```sql\nSELECT vendor_name FROM mart.dim_vendor ORDER BY 1\n```"
    monkeypatch.setattr(chatbot, "data_is_sample_only", lambda conn: True)
    output = chatbot.ask("Which vendor?", mart)
    assert output["blocked"] is None
    assert output["sql"].endswith("LIMIT 200")
    assert list(output["result"]["vendor_name"]) == ["Harbor Fresh Foods", "Sunrise Meat Co."]
    assert output["answer"] == "We spent the most with Harbor Fresh Foods."
    assert "Harbor" not in prompts[0]                    # the SQL prompt carries no data


def test_ask_blocks_unsafe_query(mart, fake_gemini):
    replies, _ = fake_gemini
    replies["Delete everything"] = "DELETE FROM mart.fact_purchase_line"
    output = chatbot.ask("Delete everything", mart)
    assert output["blocked"] == "only SELECT queries are allowed"
    assert output["result"] is None
    count = mart.execute("SELECT count(*) FROM mart.fact_purchase_line").fetchone()[0]
    assert count == 4


def test_no_answer_sent_for_real_data(mart, fake_gemini, monkeypatch):
    replies, prompts = fake_gemini
    replies["Which vendor?"] = "SELECT vendor_name FROM mart.dim_vendor"
    monkeypatch.setattr(config, "ALLOW_EXTERNAL_AI_ON_PRIVATE", False)
    monkeypatch.setattr(chatbot, "data_is_sample_only", lambda conn: False)
    output = chatbot.ask("Which vendor?", mart)
    assert output["answer"] is None
    assert len(prompts) == 1                              # only the SQL prompt, no results sent


def test_test_data_is_not_sample_data(mart):
    # make_approved_receipt uses made-up hashes, not the sample images
    assert chatbot.data_is_sample_only(mart) is False


def test_evaluate_scores_correct_and_blocked(mart, fake_gemini):
    replies, _ = fake_gemini
    for item in QUESTIONS["questions"]:
        replies[item["question"]] = item["expected_sql"]      # a "perfect" model
    for question in QUESTIONS["unsafe_questions"]:
        replies[question] = "DROP TABLE mart.fact_purchase_line"
    summary = chatbot.evaluate(QUESTIONS, app_conn=mart)
    assert summary["correct"] == 25
    assert summary["unsafe_blocked"] == 5


def test_evaluate_counts_wrong_answers(mart, fake_gemini):
    subset = {"questions": QUESTIONS["questions"][:2], "unsafe_questions": []}
    # unknown questions get "SELECT 1 FROM mart.dim_vendor": wrong answers
    summary = chatbot.evaluate(subset, app_conn=mart)
    assert summary["correct"] == 0


def test_chatbot_page_without_key_explains_setup(mart, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "9_Chatbot.py"))
    app.session_state["role"] = "developer"
    app.run()
    assert not app.exception
    assert "GEMINI_API_KEY" in app.info[0].value
