Quick Start (Windows / macOS)
Prerequisites

Python 3 installed (recommended 3.11–3.13)

pip available (usually included with Python)

This project can run without a virtual environment, but using a venv is recommended for stability.

How the launcher scripts work

The launchers do not install Python or pip. You must have Python + pip already.

On first run, the launcher checks whether uvicorn is available:

If uvicorn is missing, it runs:

python3 -m pip install -r backend/requirements.txt

If uvicorn is already installed, it skips installation and starts the server.


:) Run the app
Windows

Double-click:

run.bat

Or run in PowerShell from the project root:

.\run.bat

macOS

Make the launcher executable once:

chmod +x run.command

Then double-click run.command (or run from Terminal):

./run.command

If macOS blocks it (“developer cannot be verified”):

System Settings → Privacy & Security → Open Anyway

Or right-click run.command → Open

App URL:

http://127.0.0.1:8000/

Stop with Ctrl+C.

Troubleshooting
“passages.json is missing”

Place your JSON bank here:

backend/data/passages.json

Dependencies fail to install (first run)

Try:

Using a virtual environment (recommended), or

macOS user scope:

python3 -m pip install --user -r backend/requirements.txt
“Port 8000 is already in use”

Stop the other process or change the port in run.bat / run.command.