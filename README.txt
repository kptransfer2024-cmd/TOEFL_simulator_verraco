Quick Start (Windows / macOS)
Prerequisites

Python 3 installed (recommended: 3.11–3.13).

pip available (usually included with Python).

This project can run without a virtual environment, but using a venv is recommended for stability.

How the launcher scripts work
What gets installed, and when?

The launchers do not install Python or pip. You must have Python + pip already.

On the first run, the launcher checks whether uvicorn is available:

If uvicorn is missing, it runs pip install -r backend/requirements.txt

If uvicorn is already installed, it skips installation and starts the server

So typically:

First run: installs dependencies (once)

Later runs: just starts the app

1) Prepare the question bank (Phase 1 data)

Before launching the web app, generate passages.json:

From the project root:

python3 backend/scripts/import_pdf_to_json.py


This creates:

backend/data/passages.json

backend/data/import_report.json

If passages.json is missing, the launcher will stop and tell you to run the importer.

2) Run the app
:) Windows

Double-click:

run.bat

Or run in PowerShell from the project root:

.\run.bat

:) macOS

Make the launcher executable once:

chmod +x run.command


Then double-click run.command (or run from Terminal):

./run.command


The app will start at:

http://127.0.0.1:8000/

Stop with Ctrl+C.

Troubleshooting
“Port 8000 is already in use”

Another process is using the port. Stop it or change the port in the launcher scripts.

“pip is not available”

Your Python installation is missing pip. Reinstall Python with pip enabled.

Page opens but shows an error

Check the terminal output: the real error is printed there (e.g., import errors or missing files).

Dependencies fail to install (first run)

Network/permissions can block pip install. Try:

Using a virtual environment (recommended)

Or on macOS, install with user scope:

python3 -m pip install --user -r backend/requirements.txt