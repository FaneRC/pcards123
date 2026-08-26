# OSU P-Card Audit Lab

A Streamlit application for the Analytics Mindset P-card case. It provides:

1. An AI assistant that translates natural-language audit questions into safe,
   read-only SQLite queries.
2. A prohibited-purchases dashboard with separate description and vendor searches.

The source database contains OSU P-card transactions for 2010–2014.

## Files

- `streamlit_app.py` — complete application
- `pcards.db` — supplied SQLite database
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — visual theme and server settings
- `.streamlit/secrets.toml.example` — API-key template

## Run locally

1. Install Python 3.11 or newer.
2. Open a terminal in this folder.
3. Create and activate a virtual environment.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and replace
   the placeholder with a Gemini API key from Google AI Studio. Never commit
   `secrets.toml`.
6. Start the application:

   ```bash
   streamlit run streamlit_app.py
   ```

The dashboard works without an API key. The “Ask the database” tab requires one.

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload these files. The database is about 90 MB,
   which is close to GitHub's single-file limit. Git LFS is preferable for classroom
   distribution, or the instructor can provide a smaller 2014-only database.
2. Sign in at <https://share.streamlit.io> and connect the GitHub repository.
3. Select `streamlit_app.py` as the entrypoint.
4. Open **Advanced settings** and add:

   ```toml
   GEMINI_API_KEY = "your-key"
   GEMINI_MODEL = "gemini-3.5-flash-lite"
   ```

5. Deploy and copy the resulting `streamlit.app` URL.

## Security controls

- The SQLite database is opened in read-only and query-only modes.
- AI output must begin with `SELECT` or `WITH` and cannot contain multiple statements.
- Data-changing and administrative SQL keywords are rejected.
- SQLite's authorizer rejects operations outside reading, selection, and built-in
  functions.
- Detailed AI results are limited to 500 displayed rows.
- Dashboard values use SQL parameters rather than string interpolation.
- The Gemini API key is read from Streamlit secrets or an environment variable and should
  never appear in the repository.

AI-generated queries can still be incomplete or analytically inappropriate. Auditors
must inspect the generated SQL and corroborate flagged transactions before concluding
that an internal-control violation occurred.
