"""
run.py — Startup script for ControlPlane.ai

Starts FastAPI backend and Streamlit frontend.
Run from the project root: python run.py
"""

import subprocess
import sys
import os
import time
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_backend():
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--reload",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--log-level", "info",
        ],
        cwd=ROOT,
    )


def run_frontend():
    time.sleep(2)  # give backend a moment to start
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run",
            os.path.join(ROOT, "frontend", "app.py"),
            "--server.port", "8501",
            "--server.address", "localhost",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("  ControlPlane.ai - AI Risk Decision Layer")
    print("  Round 2 - Accenture Innovation Challenge 2026")
    print("=" * 60)
    print()
    print("  Starting backend  -> http://localhost:8000")
    print("  Starting frontend -> http://localhost:8501")
    print("  API docs          -> http://localhost:8000/docs")
    print()
    print("  Press Ctrl+C to stop both servers.")
    print("=" * 60)

    backend_thread = threading.Thread(target=run_backend, daemon=True)
    frontend_thread = threading.Thread(target=run_frontend, daemon=True)

    backend_thread.start()
    frontend_thread.start()

    try:
        backend_thread.join()
        frontend_thread.join()
    except KeyboardInterrupt:
        print("\nShutting down ControlPlane.ai...")
