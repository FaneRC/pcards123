"""Replace P-card cardholder names with stable synthetic pseudonyms.

The script creates ``pcards.original.db`` once as a local recovery copy. The
backup is excluded from Git. Re-running the script against an already
anonymized database is refused.
"""

from __future__ import annotations

import random
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "pcards.db"
BACKUP = ROOT / "pcards.original.db"
SEED = 20260826


def database_metrics(connection: sqlite3.Connection) -> tuple[int, float, int]:
    return connection.execute(
        "SELECT COUNT(*), ROUND(COALESCE(SUM(Amount), 0), 2), COUNT(DISTINCT ID) FROM pcards"
    ).fetchone()


def main() -> None:
    if not DATABASE.exists():
        raise FileNotFoundError(DATABASE)

    with sqlite3.connect(DATABASE) as check:
        if check.execute(
            "SELECT COUNT(*) FROM pcards WHERE FullName GLOB 'Employee [0-9A-F]*'"
        ).fetchone()[0]:
            raise RuntimeError("Database appears to be anonymized already; no changes made.")
        before_metrics = database_metrics(check)

    if not BACKUP.exists():
        shutil.copy2(DATABASE, BACKUP)

    with sqlite3.connect(DATABASE) as connection:
        identities = connection.execute(
            """SELECT DISTINCT FullName, CardholderLastName, CardholderFirstInitial
               FROM pcards
               ORDER BY FullName, CardholderLastName, CardholderFirstInitial"""
        ).fetchall()

        rng = random.Random(SEED)
        tokens: set[str] = set()
        while len(tokens) < len(identities):
            tokens.add(f"{rng.randrange(16**8):08X}")

        mapping = []
        for identity, token in zip(identities, sorted(tokens)):
            full_name, last_name, first_initial = identity
            mapping.append(
                (
                    f"Employee {token}",
                    f"Employee{token}",
                    "E",
                    full_name,
                    last_name,
                    first_initial,
                )
            )

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TEMP TABLE name_map (
                   NewFullName TEXT NOT NULL,
                   NewLastName TEXT NOT NULL,
                   NewFirstInitial TEXT NOT NULL,
                   OldFullName TEXT NOT NULL,
                   OldLastName TEXT NOT NULL,
                   OldFirstInitial TEXT NOT NULL,
                   PRIMARY KEY (OldFullName, OldLastName, OldFirstInitial)
               ) WITHOUT ROWID"""
        )
        connection.executemany(
            "INSERT INTO name_map VALUES (?, ?, ?, ?, ?, ?)", mapping
        )
        connection.execute(
            """UPDATE pcards
               SET (FullName, CardholderLastName, CardholderFirstInitial) = (
                   SELECT NewFullName, NewLastName, NewFirstInitial
                   FROM name_map
                   WHERE OldFullName = pcards.FullName
                     AND OldLastName = pcards.CardholderLastName
                     AND OldFirstInitial = pcards.CardholderFirstInitial
               )"""
        )
        connection.commit()

        after_metrics = database_metrics(connection)
        remaining_original = connection.execute(
            "SELECT COUNT(*) FROM pcards WHERE FullName NOT GLOB 'Employee [0-9A-F]*'"
        ).fetchone()[0]
        distinct_after = connection.execute(
            "SELECT COUNT(DISTINCT FullName) FROM pcards"
        ).fetchone()[0]

    if after_metrics != before_metrics or remaining_original != 0:
        shutil.copy2(BACKUP, DATABASE)
        raise RuntimeError("Verification failed; the original database was restored.")

    print(f"Anonymized {len(identities):,} identities across {after_metrics[0]:,} rows.")
    print(f"Distinct synthetic names: {distinct_after:,}")
    print(f"Preserved row count / amount / distinct IDs: {after_metrics}")
    print(f"Recovery copy: {BACKUP}")


if __name__ == "__main__":
    main()
