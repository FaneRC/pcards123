import ast
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest


SOURCE = Path(__file__).with_name("streamlit_app.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def test_application_is_valid_python():
    assert TREE is not None


def test_database_and_core_files_exist():
    root = Path(__file__).parent
    assert (root / "pcards.db").exists()
    assert (root / "requirements.txt").exists()
    assert (root / ".streamlit" / "config.toml").exists()


def test_security_controls_are_present():
    assert "mode=ro" in SOURCE
    assert "PRAGMA query_only = ON" in SOURCE
    assert "set_authorizer" in SOURCE
    assert "Only read-only SELECT queries are allowed" in SOURCE
    assert "LIMIT {DISPLAY_LIMIT + 1}" in SOURCE


def test_streamlit_app_starts_without_exceptions():
    app = AppTest.from_file(str(Path(__file__).with_name("streamlit_app.py")))
    app.run(timeout=30)
    assert not app.exception
    assert len(app.tabs) == 4  # two main tabs plus two search tabs
    assert app.title[0].value == "OSU P-Card Audit Lab"


def test_known_dashboard_searches_return_results():
    database = Path(__file__).with_name("pcards.db")
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        description_count = connection.execute(
            """SELECT COUNT(*) FROM pcards
               WHERE Year = ? AND LOWER(COALESCE(Description, '')) LIKE ?""",
            (2014, "%alcohol%"),
        ).fetchone()[0]
        vendor_count = connection.execute(
            """SELECT COUNT(*) FROM pcards
               WHERE Year = ? AND LOWER(COALESCE(Vendor, '')) LIKE ?""",
            (2014, "%post office%"),
        ).fetchone()[0]
    assert description_count > 0
    assert vendor_count > 0
