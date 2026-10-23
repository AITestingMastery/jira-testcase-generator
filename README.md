# Jira Ticket to Test Case Generator

Generate reviewable test cases from a Jira issue or pasted ticket content. The app uses **Streamlit** for the UI and **FastAPI** for its local API.

# Integrated Jira and email workflow:** 
Jira issue fetching uses the configured Jira authentication mode (basic credentials or a personal access token). After generating test cases, the app can email the results through an authenticated SMTP account. Store the required credentials in the project-root `.env` file.

## Framework Architecture

```
Project root
|-- streamlit_app.py       Streamlit UI and local API startup
|-- main.py                FastAPI app and HTTP routes
|-- requirements.txt       Python dependencies
|-- .env.example           Credentials and settings template
|-- .env                   Your local credentials (create this)
|-- src/
|   |-- jira_service.py    Jira API requests and issue text parsing
|   |-- nlp_service.py     OpenAI call and test case validation
|   |-- email_service.py   Email delivery through SMTP
|   `-- __init__.py        Python package marker
|-- .gitignore             Ignores secrets, virtual environments, and caches
`-- README.md              Setup and project guide
```

FastAPI loads `.env` once at startup using `python-dotenv`. Route handlers and services read the settings they need directly from environment variables. The `/api/settings` route returns only readiness flags, never credentials.

## Main components

| File | Framework or library | Responsibility |
|---|---|---|
| `streamlit_app.py` | Streamlit | Ticket input, results, CSV download, and email form; starts the local API if needed. |
| `main.py` | FastAPI, Pydantic, python-dotenv | Loads `.env`, validates API requests, and exposes the application endpoints. |
| `src/jira_service.py` | HTTPX | Fetches Jira issues and parses descriptions and comments. |
| `src/nlp_service.py` | HTTPX, Pydantic | Calls OpenAI and validates generated test cases. |
| `src/email_service.py` | Python `smtplib` | Sends generated test cases through SMTP. |
| `requirements.txt` | pip | Lists dependencies for the UI and API. |

## Quick start (Windows)

### 1. Configure credentials

Copy the example settings file and fill in your Jira and OpenAI credentials. Add SMTP settings if you want to use email.

```powershell
Copy-Item .env.example .env
```

### 2. Install dependencies

Run these commands from the project root. The virtual environment only needs to be created and populated once.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Start the app

From the project root, run:

```powershell
streamlit run streamlit_app.py
```


The UI uses `http://localhost:8000` by default. To use a different API address, set `BACKEND_URL` before starting Streamlit. The sidebar shows the configured OpenAI model and whether Jira, OpenAI, and optional email settings are present.

