Dexter Python backend scaffold

This folder contains a minimal FastAPI + Typer scaffold to begin porting the TypeScript Dexter backend to Python.

Quick start (Windows PowerShell):

1. Create and activate a virtualenv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Run the API server:

```powershell
python -m uvicorn app.main:app --reload
```

4. Use the CLI locally:

```powershell
python cli.py ask "What is the date today?"
```
