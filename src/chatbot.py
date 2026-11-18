"""Read-only text-to-SQL chatbot over the mart (star schema).

Flow for one question:
    1. Gemini gets ONLY the mart schema description + the question (no data)
       and returns one SQL query.
    2. The SQL is treated as untrusted: sqlglot parses it, and only a single
       SELECT reading mart.* objects is allowed. LIMIT 200 is added if missing.
    3. It runs as the receipts_readonly role (SELECT on mart only), in a
       read-only transaction with a 5 second statement timeout.
    4. Optional one-line answer: this sends the (small) result table to Gemini,
       so it only runs on sample data unless ALLOW_EXTERNAL_AI_ON_PRIVATE=true.

Evaluate on tests/chatbot_questions.json (needs GEMINI_API_KEY):
    python -m src.chatbot --evaluate
"""

import argparse
import json
import re
from decimal import Decimal

import pandas as pd
import sqlglot
from sqlglot import exp

from src import config
from src.db import get_connection

MAX_ROWS = 200
STATEMENT_TIMEOUT = "5s"
QUESTIONS_FILE = config.PROJECT_ROOT / "tests" / "chatbot_questions.json"

# Statement types that change data or the database. Any of them anywhere -> blocked.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Into, exp.Grant, exp.Set, exp.Copy,
)
# Server functions that can read files, sleep, or change settings
FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting",
                               "query_to_xml", "txid_", "nextval", "setval")
ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


class BlockedQuery(Exception):
    """The generated SQL is not a safe read-only query on the mart."""


# ---------------------------------------------------------------------------
# 1. Schema description (structure only, never data)
# ---------------------------------------------------------------------------
SCHEMA_NOTES = """Notes:
- Only approved receipts are in the mart. Grain of mart.fact_purchase_line: one line item on one receipt.
- Money columns are in dollars. unit_price_standard and the views' prices are per standard unit
  (dim_item.standard_unit: lb, each or L). standard_quantity is in that unit.
- mart.dim_date.date_key is YYYYMMDD; date_key 0 means unknown date (full_date is NULL).
- mart.dim_item.item_name 'UNMAPPED' means the line has no item rule yet.
- mart.v_price_history: price per item/vendor/date with previous_price and pct_change.
- mart.v_price_alerts: rows of v_price_history above the price-alert threshold.
- mart.v_supplier_comparison / mart.v_supplier_savings: items bought from 2+ suppliers;
  estimated_monthly_savings is an ESTIMATE."""


def schema_description(conn):
    """'mart.table(column type, ...)' lines for every mart table and view."""
    rows = conn.execute(
        """
        SELECT c.table_name, c.column_name, c.data_type
        FROM information_schema.columns c
        WHERE c.table_schema = 'mart'
        ORDER BY c.table_name, c.ordinal_position
        """
    ).fetchall()
    tables = {}
    for table, column, data_type in rows:
        tables.setdefault(table, []).append(f"{column} {data_type}")
    lines = [f"mart.{table}({', '.join(columns)})" for table, columns in tables.items()]
    return "\n".join(lines) + "\n\n" + SCHEMA_NOTES


# ---------------------------------------------------------------------------
# 2. Gemini
# ---------------------------------------------------------------------------
SQL_PROMPT = """You write PostgreSQL queries for a restaurant's purchasing data.
Use ONLY these tables and views, always with the schema prefix (mart.):

{schema}

Write ONE SELECT query that answers the question below. Return only the SQL,
no explanation and no markdown.

Question: {question}"""

ANSWER_PROMPT = """Question: {question}
Query result (CSV):
{table}

Answer the question in one short plain-English sentence using only this result."""


def _call_gemini_text(prompt):
    """The only function that talks to the Gemini API here. Tests replace it."""
    from google.genai import types

    from src import gemini_client
    return gemini_client.generate(prompt, types.GenerateContentConfig(temperature=0))


def extract_sql(text):
    """Remove ```sql fences and surrounding whitespace from the model's answer."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    return text


def generate_sql(question, schema):
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return extract_sql(_call_gemini_text(SQL_PROMPT.format(schema=schema, question=question)))


# ---------------------------------------------------------------------------
# 3. Validation of untrusted SQL
# ---------------------------------------------------------------------------
def validate_sql(sql):
    """Return safe SQL (with a LIMIT) or raise BlockedQuery with the reason."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError:
        raise BlockedQuery("the SQL could not be parsed")
    if len(statements) != 1:
        raise BlockedQuery("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, ALLOWED_ROOTS):
        raise BlockedQuery("only SELECT queries are allowed")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise BlockedQuery(f"{type(node).__name__.upper()} is not allowed")

    # Every table must be a mart object (or a WITH ... name defined in the query)
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        schema = (table.db or "").lower()
        name = table.name.lower()
        if schema == "" and name in cte_names:
            continue
        if schema != "mart":
            raise BlockedQuery(f"only mart tables are allowed (found {table.sql()})")

    for function in tree.find_all(exp.Func):
        name = (function.sql_name() if not isinstance(function, exp.Anonymous) else function.name).lower()
        if name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise BlockedQuery(f"function {name} is not allowed")

    # Add LIMIT 200 if missing, or lower a bigger one
    limit = tree.args.get("limit")
    current = None
    if limit is not None and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        current = int(limit.expression.this)
    if current is None or current > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="postgres")


# ---------------------------------------------------------------------------
# 4. Running and answering
# ---------------------------------------------------------------------------
def run_readonly(sql):
    """Run validated SQL as receipts_readonly. Returns a DataFrame."""
    with get_connection(readonly=True) as conn:
        with conn.transaction():
            # Belt and braces: the role can only SELECT on mart anyway
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
            cursor = conn.execute(sql)
            columns = [col.name for col in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)


def data_is_sample_only(conn):
    """True if every stored image is one of the fake sample receipts (by hash)."""
    from src.ocr import sample_hashes
    hashes = [row[0] for row in conn.execute("SELECT sha256 FROM raw.receipt_file").fetchall()]
    allowed = sample_hashes()
    return all(h in allowed for h in hashes)


def answer_allowed(app_conn):
    return config.ALLOW_EXTERNAL_AI_ON_PRIVATE or data_is_sample_only(app_conn)


def answer_in_words(question, result):
    table = result.head(20).to_csv(index=False)
    return _call_gemini_text(ANSWER_PROMPT.format(question=question, table=table)).strip()


def ask(question, app_conn, sql_generator=None):
    """Answer one question. Returns a dict for the page:
    {"sql", "result" (DataFrame or None), "blocked" (reason or None), "error", "answer"}

    sql_generator: optional replacement for generate_sql (the page passes a
    cached version, so asking the same question again is instant).
    """
    sql_generator = sql_generator or generate_sql
    output = {"sql": None, "result": None, "blocked": None, "error": None, "answer": None}
    output["sql"] = sql_generator(question, schema_description(app_conn))
    try:
        safe_sql = validate_sql(output["sql"])
    except BlockedQuery as reason:
        output["blocked"] = str(reason)
        return output
    output["sql"] = safe_sql
    try:
        output["result"] = run_readonly(safe_sql)
    except Exception as error:
        output["error"] = type(error).__name__
        return output
    if answer_allowed(app_conn):
        output["answer"] = answer_in_words(question, output["result"])
    return output


# ---------------------------------------------------------------------------
# 5. Evaluation
# ---------------------------------------------------------------------------
def _normalize(value):
    """Make values comparable: numbers rounded to 2 decimals, text lowercased."""
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"
    return str(value).strip().lower()


def results_match(expected, actual):
    """Correct if same number of rows and every expected column's values
    appear as one of the actual columns (column names and order don't matter)."""
    if actual is None or len(expected) != len(actual):
        return False
    actual_columns = [sorted(_normalize(v) for v in actual[c]) for c in actual.columns]
    for column in expected.columns:
        wanted = sorted(_normalize(v) for v in expected[column])
        if wanted not in actual_columns:
            return False
    return True


def evaluate(questions=None, app_conn=None):
    """Score the chatbot on the question file. Returns a summary dict."""
    if questions is None:
        questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    own = app_conn is None
    app_conn = app_conn or get_connection()
    try:
        schema = schema_description(app_conn)
        correct, details = 0, []
        for item in questions["questions"]:
            expected = run_readonly(item["expected_sql"])
            outcome = "wrong"
            try:
                actual = run_readonly(validate_sql(generate_sql(item["question"], schema)))
                if results_match(expected, actual):
                    outcome = "correct"
                    correct += 1
            except BlockedQuery:
                outcome = "blocked"
            except Exception as error:
                outcome = f"error: {type(error).__name__}"
            details.append({"question": item["question"], "outcome": outcome})

        # Unsafe requests: count how many the validator blocked. Anything that
        # gets through is, by construction, a read-only SELECT on the mart.
        blocked = 0
        for question in questions["unsafe_questions"]:
            try:
                validate_sql(generate_sql(question, schema))
            except BlockedQuery:
                blocked += 1
        return {"correct": correct, "total": len(questions["questions"]),
                "unsafe_questions": len(questions["unsafe_questions"]), "unsafe_blocked": blocked,
                "details": details}
    finally:
        if own:
            app_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Text-to-SQL chatbot.")
    parser.add_argument("--evaluate", action="store_true", help="score on tests/chatbot_questions.json")
    parser.add_argument("question", nargs="?", help="ask one question")
    args = parser.parse_args()
    if args.evaluate:
        summary = evaluate()
        print(json.dumps(summary, indent=2))
        print(f"Chatbot accuracy: {summary['correct']}/{summary['total']}; "
              f"unsafe requests blocked: {summary['unsafe_blocked']}/{summary['unsafe_questions']}")
    elif args.question:
        with get_connection() as conn:
            output = ask(args.question, conn)
        print(output["sql"])
        print(output["blocked"] or output["error"] or output["result"])
        if output["answer"]:
            print(output["answer"])


if __name__ == "__main__":
    main()
