from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "pcards.db"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DISPLAY_LIMIT = 500

RESULT_COLUMNS = [
    "Year",
    "Month",
    "ID",
    "FullName",
    "AgencyName",
    "Description",
    "Amount",
    "Vendor",
    "TransactionDate",
    "PostedDate",
    "MCC",
]

PROHIBITED_CATEGORIES = {
    "Alcohol": ["alcohol", "beer", "wine", "liquor"],
    "Cash, advances, and ATM": ["cash", "advance", "atm"],
    "Decorations": ["decoration", "decor", "balloon", "floral"],
    "Donations and sponsorships": ["donation", "sponsor"],
    "Gasoline": ["gasoline", "fuel", "gas"],
    "Gifts and gift cards": ["gift", "gift card", "certificate"],
    "Insurance": ["insurance"],
    "Late fees": ["late fee", "penalty"],
    "Mail and postage": ["postage", "post office", "postal", "ups", "fedex"],
    "Moving expenses": ["moving", "relocation"],
    "Personal purchases": ["personal"],
    "Memberships and dues": ["membership", "dues"],
    "Salaries, wages, and benefits": ["salary", "wage", "benefit", "payroll"],
    "Service and incentive awards": ["award", "incentive", "employee recognition"],
}

SQL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sql": {"type": "string"},
        "interpretation": {"type": "string"},
    },
    "required": ["title", "sql", "interpretation"],
}

AI_INSTRUCTIONS = f"""
You are an internal-audit data analyst. Translate the user's question into one
read-only SQLite query against the single table named pcards.

Schema:
Year INTEGER, Month INTEGER, FullName TEXT, ID INTEGER, AgencyNumber INTEGER,
AgencyName TEXT, CardholderLastName TEXT, CardholderFirstInitial TEXT,
Description TEXT, Amount REAL, Vendor TEXT, TransactionDate TEXT,
PostedDate TEXT, MCC TEXT.

Rules:
- Return exactly one SELECT statement. A WITH clause followed by SELECT is allowed.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, ATTACH, DETACH, PRAGMA,
  VACUUM, REINDEX, ANALYZE, transaction statements, or user-defined functions.
- Use SQLite syntax only.
- Use case-insensitive text matching with LOWER(COALESCE(field, '')) LIKE '%term%'.
- TransactionDate and PostedDate are stored as M/D/YYYY H:MM:SS text. Prefer the
  Year and Month columns for calendar filtering.
- Unless the user asks for a summary or count, include useful follow-up fields:
  ID, Year, FullName, Description, Amount, Vendor, TransactionDate, PostedDate, MCC.
- If the user does not request a year, do not invent one.
- Do not claim a policy violation. Describe matches as potential exceptions.
- Keep the interpretation to one short sentence explaining what the query returns.
- The application independently caps detailed output at {DISPLAY_LIMIT} rows.
""".strip()


st.set_page_config(
    page_title="OSU P-Card Audit Lab",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root { --osu-orange: #c75300; --ink: #17202a; --soft: #f6f3ee; }
    .stApp { background: linear-gradient(180deg, #fbfaf8 0, #ffffff 20rem); }
    .block-container { max-width: 1180px; padding-top: 2.2rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
    h1 { border-left: 0.38rem solid var(--osu-orange); padding-left: 0.85rem; }
    div[data-testid="stMetric"] {
        background: white; border: 1px solid #e6dfd6; border-radius: 0.75rem;
        padding: 0.75rem 1rem; box-shadow: 0 2px 10px rgba(23,32,42,.04);
    }
    .audit-note {
        background: #fff7ed; border: 1px solid #fed7aa; border-radius: .65rem;
        color: #7c2d12; padding: .8rem 1rem; margin: .5rem 0 1.25rem;
    }
    .small-muted { color: #5f6b76; font-size: .92rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #e6dfd6; border-radius: .6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a deployment secret first and fall back to an environment variable."""
    try:
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    return str(value) if value else os.getenv(name, default)


def connect_read_only() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 3000")
    return connection


@st.cache_data(show_spinner=False)
def available_years() -> list[int]:
    with connect_read_only() as connection:
        rows = connection.execute(
            "SELECT DISTINCT Year FROM pcards WHERE Year IS NOT NULL ORDER BY Year DESC"
        ).fetchall()
    return [int(row[0]) for row in rows]


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    return df


def dataframe_config(df: pd.DataFrame) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if "Amount" in df.columns:
        config["Amount"] = st.column_config.NumberColumn("Amount", format="$%.2f")
    if "ID" in df.columns:
        config["ID"] = st.column_config.NumberColumn("Transaction ID", format="%d")
    return config


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def render_results(
    df: pd.DataFrame,
    *,
    key: str,
    filename: str,
    capped: bool = False,
) -> None:
    df = normalize_dataframe(df)
    left, middle, right = st.columns(3)
    left.metric("Matching rows", f"{len(df):,}" + ("+" if capped else ""))
    if "Amount" in df.columns:
        middle.metric("Net amount shown", f"${df['Amount'].sum():,.2f}")
        right.metric("Largest amount shown", f"${df['Amount'].max():,.2f}" if len(df) else "$0.00")
    else:
        middle.metric("Columns returned", len(df.columns))
        right.metric("Display limit", f"{DISPLAY_LIMIT:,}")

    if capped:
        st.warning(
            f"More than {DISPLAY_LIMIT:,} rows matched. The preview and download contain "
            f"the first {DISPLAY_LIMIT:,} rows; refine the question for a complete population."
        )

    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config=dataframe_config(df),
        height=min(620, 110 + max(len(df), 1) * 35),
    )
    st.download_button(
        "Download displayed results as CSV",
        data=csv_bytes(df),
        file_name=filename,
        mime="text/csv",
        key=f"download_{key}",
    )


def ensure_safe_select(sql: str) -> str:
    candidate = sql.strip()
    candidate = re.sub(r"^```(?:sql)?\s*|\s*```$", "", candidate, flags=re.I).strip()
    if candidate.endswith(";"):
        candidate = candidate[:-1].strip()
    if not candidate or ";" in candidate:
        raise ValueError("The AI response must contain exactly one SQL statement.")
    if not re.match(r"^(SELECT|WITH)\b", candidate, flags=re.I):
        raise ValueError("Only read-only SELECT queries are allowed.")

    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|"
        r"PRAGMA|VACUUM|REINDEX|ANALYZE|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b",
        flags=re.I,
    )
    if forbidden.search(candidate):
        raise ValueError("The generated query contains a prohibited SQL operation.")
    return candidate


def execute_ai_query(sql: str) -> tuple[pd.DataFrame, bool]:
    safe_sql = ensure_safe_select(sql)
    wrapped = f"SELECT * FROM ({safe_sql}) AS audit_result LIMIT {DISPLAY_LIMIT + 1}"

    with connect_read_only() as connection:
        allowed_actions = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }

        def authorizer(action: int, _arg1: str, _arg2: str, _db: str, _source: str) -> int:
            return sqlite3.SQLITE_OK if action in allowed_actions else sqlite3.SQLITE_DENY

        connection.set_authorizer(authorizer)
        df = pd.read_sql_query(wrapped, connection)

    capped = len(df) > DISPLAY_LIMIT
    return df.head(DISPLAY_LIMIT), capped


def ask_model(question: str) -> dict[str, str]:
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No Gemini API key is configured. Add GEMINI_API_KEY in Streamlit secrets."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = get_secret("GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    response = client.models.generate_content(
        model=model,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=AI_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=SQL_OUTPUT_SCHEMA,
            max_output_tokens=1200,
            temperature=0.1,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")
    return json.loads(response.text)


@st.cache_data(show_spinner=False, ttl=300)
def dashboard_search(year: int, field: str, keyword: str) -> tuple[pd.DataFrame, int, float]:
    if field not in {"Description", "Vendor"}:
        raise ValueError("Unsupported search field")
    pattern = f"%{keyword.strip().lower()}%"
    where = f"Year = ? AND LOWER(COALESCE({field}, '')) LIKE ?"

    with connect_read_only() as connection:
        count, total = connection.execute(
            f"SELECT COUNT(*), COALESCE(SUM(Amount), 0) FROM pcards WHERE {where}",
            (year, pattern),
        ).fetchone()
        query = f"""
            SELECT {', '.join(RESULT_COLUMNS)}
            FROM pcards
            WHERE {where}
            ORDER BY ABS(Amount) DESC, TransactionDate ASC, ID ASC
            LIMIT ?
        """
        df = pd.read_sql_query(query, connection, params=(year, pattern, DISPLAY_LIMIT))
    return df, int(count), float(total)


def render_search_panel(field: str, year: int, key: str) -> None:
    label = "transaction description" if field == "Description" else "vendor name"
    example = "alcohol, gift card, membership" if field == "Description" else "post office, liquor, shell"
    st.markdown(f"#### {field} search")
    st.caption(f"Searches only the **{field}** field using a case-insensitive partial match.")

    with st.form(f"{key}_form"):
        keyword = st.text_input(
            f"Keyword or phrase in the {label}",
            placeholder=example,
            key=f"{key}_keyword",
        )
        submitted = st.form_submit_button(f"Search {field.lower()}", type="primary")

    if not submitted:
        return
    if not keyword.strip():
        st.warning("Enter a keyword or phrase before searching.")
        return

    with st.spinner("Searching transactions…"):
        df, total_count, total_amount = dashboard_search(year, field, keyword)

    st.markdown(f"**Search evidence:** {year} · {field} contains “{keyword.strip()}”")
    if total_count == 0:
        st.info("No matching transactions were found. Try a broader or related term.")
        return

    shown = len(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Matching transactions", f"{total_count:,}")
    c2.metric("Net matching amount", f"${total_amount:,.2f}")
    c3.metric("Rows displayed", f"{shown:,}")
    if total_count > shown:
        st.warning(
            f"The search found {total_count:,} rows. The table and download show the "
            f"{DISPLAY_LIMIT:,} largest transactions by absolute amount."
        )
    st.dataframe(
        normalize_dataframe(df),
        width="stretch",
        hide_index=True,
        column_config=dataframe_config(df),
        height=min(620, 110 + max(len(df), 1) * 35),
    )
    st.download_button(
        "Download displayed results as CSV",
        csv_bytes(df),
        file_name=f"pcard_{year}_{field.lower()}_{re.sub(r'[^a-z0-9]+', '_', keyword.lower()).strip('_')}.csv",
        mime="text/csv",
        key=f"{key}_download",
    )

    with st.expander("Suggested follow-up documentation"):
        st.markdown(
            f"""
            - **Year searched:** {year}
            - **Search type:** {field} search
            - **Search term:** `{keyword.strip()}`
            - **Results identified:** {total_count:,} transaction(s), net amount ${total_amount:,.2f}
            - **Additional testing:** Inspect receipts, business-purpose documentation, approvals,
              MCC classification, related credits, and any documented policy exception. A keyword
              match is a risk indicator and does not establish a violation.
            """
        )


st.title("OSU P-Card Audit Lab")
st.markdown(
    "Use AI-assisted analysis and targeted keyword searches to identify transactions that may "
    "require additional audit testing."
)
st.markdown(
    '<div class="audit-note"><strong>Audit caution:</strong> Results are potential exceptions, '
    "not confirmed violations. Review receipts, business purpose, approvals, credits, and policy "
    "exceptions before reaching a conclusion.</div>",
    unsafe_allow_html=True,
)

if not DB_PATH.exists():
    st.error("The application cannot find `pcards.db`. Place it in the repository root.")
    st.stop()

ai_tab, dashboard_tab = st.tabs(["Ask the database", "Prohibited purchases dashboard"])

with ai_tab:
    st.header("Ask the database")
    st.write(
        "Ask a question in ordinary language. The AI converts it into a read-only SQLite query; "
        "you can inspect the query before relying on the results."
    )
    st.caption(
        "Examples: “Which employees spent the most in 2014?” · “Show transactions over $5,000” · "
        "“Total 2014 spending by vendor”"
    )

    configured = bool(get_secret("GEMINI_API_KEY"))
    if not configured:
        st.info(
            "AI is not configured yet. Add `GEMINI_API_KEY` in `.streamlit/secrets.toml` locally "
            "or in the Streamlit Community Cloud app settings."
        )

    with st.form("ai_question_form"):
        question = st.text_area(
            "Audit question",
            placeholder="For example: Which vendors received the highest total payments in 2014?",
            height=100,
        )
        ask_submitted = st.form_submit_button(
            "Ask the database", type="primary", disabled=not configured
        )

    if ask_submitted:
        if not question.strip():
            st.warning("Enter a question before submitting.")
        else:
            try:
                with st.spinner("Translating the question and querying the database…"):
                    plan = ask_model(question.strip())
                    result_df, was_capped = execute_ai_query(plan["sql"])
                st.subheader(plan["title"])
                st.write(plan["interpretation"])
                with st.expander("Review the generated SQL"):
                    st.code(ensure_safe_select(plan["sql"]), language="sql")
                if result_df.empty:
                    st.info("The query ran successfully but returned no matching rows.")
                else:
                    render_results(
                        result_df,
                        key="ai",
                        filename="pcard_ai_query_results.csv",
                        capped=was_capped,
                    )
            except Exception as exc:
                st.error(f"The question could not be completed: {exc}")
                st.caption("Try a more specific question that names a year, field, or measure.")

with dashboard_tab:
    st.header("Prohibited purchases dashboard")
    st.markdown(
        """
        **How to use this dashboard**

        1. Select the calendar year to examine.
        2. Choose the description or vendor search below.
        3. Enter one keyword at a time and review the matching transactions.
        4. Download relevant results and document the year, term, findings, and follow-up work.
        """
    )

    years = available_years()
    default_index = years.index(2014) if 2014 in years else 0
    year = st.selectbox("Calendar year", years, index=default_index)

    with st.expander("Prohibited categories and suggested search terms"):
        for category, terms in PROHIBITED_CATEGORIES.items():
            st.markdown(f"**{category}:** {', '.join(terms)}")

    description_tab, vendor_tab = st.tabs(["Description search", "Vendor search"])
    with description_tab:
        render_search_panel("Description", int(year), "description")
    with vendor_tab:
        render_search_panel("Vendor", int(year), "vendor")

st.divider()
st.markdown(
    '<p class="small-muted">Educational audit application · Oklahoma State University P-card case · '
    "Database access is read-only.</p>",
    unsafe_allow_html=True,
)
