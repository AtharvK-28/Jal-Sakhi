"""One-command launcher for JalSakhi AI.

    python run.py            start on http://localhost:8000 (also reachable from phones on the same Wi-Fi)
    python run.py --port 9000
    python run.py --rebuild  force a fresh frontend build
    python run.py --test     run the backend test plan and exit
    python run.py --bench    time the platform on this machine (load test) and exit

Installs missing Python packages, builds the web UI once if it has not been built, trains the
ML models on first run (about two minutes), then serves the API and the UI from a single process.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
NEEDED = {"fastapi": "fastapi", "uvicorn": "uvicorn[standard]", "multipart": "python-multipart", "numpy": "numpy",
          "sklearn": "scikit-learn", "joblib": "joblib"}


def lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def ensure_python_packages():
    missing = [pip for mod, pip in NEEDED.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print(f"Installing Python packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])


def ensure_frontend(rebuild: bool):
    dist = FRONTEND / "dist" / "index.html"
    if dist.exists() and not rebuild:
        return
    npm = shutil.which("npm")
    if npm is None:
        print("Node.js / npm not found. Install Node 18+ to build the web UI; the API will still start.")
        return
    if not (FRONTEND / "node_modules").exists():
        print("Installing frontend packages (first run only)...")
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    print("Building the web UI...")
    subprocess.check_call([npm, "run", "build"], cwd=FRONTEND)


def main():
    default_port = int(os.environ.get("PORT", 8000))
    ap = argparse.ArgumentParser(description="Start JalSakhi AI")
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--host", default="0.0.0.0", help="use 127.0.0.1 to keep it off the network")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--bench", action="store_true")
    args = ap.parse_args()

    ensure_python_packages()
    if args.test:
        sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=BACKEND))
    if args.bench:
        sys.exit(subprocess.call([sys.executable, "-m", "app.bench"], cwd=BACKEND))
    ensure_frontend(args.rebuild)

    ip = lan_ip()
    print("\n  JalSakhi AI  (proof of concept, simulated data)")
    print(f"  Command centre : http://localhost:{args.port}")
    print(f"  Citizen app    : http://localhost:{args.port}/citizen")
    if ip and args.host == "0.0.0.0":
        print(f"  From a phone   : http://{ip}:{args.port}/citizen   (same Wi-Fi; allow Python through the firewall if asked)")
    print(f"  API docs       : http://localhost:{args.port}/docs")
    print("  Demo sign-in   : one click on the landing page (password for all demo accounts: jal123)\n")

    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
