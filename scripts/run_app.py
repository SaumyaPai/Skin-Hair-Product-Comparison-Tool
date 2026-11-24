"""Starts the whole app with one command: the API in the background, then the page in your browser.

Run from the project folder (with .venv active):  python -m scripts.run_app
Press Ctrl + C in this window to stop both.

If an older copy of the app is still running (for example a PowerShell window you forgot to close),
it would keep answering on the same ports and you'd see the OLD page. So before starting, this script
looks for anything already using ports 8000 and 8501. If it is an old copy of this app (Python), it is
stopped. If it is some other program, nothing is stopped and you're told what to do."""
import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API_PORT, PAGE_PORT = 8000, 8501
API_URL = f"http://localhost:{API_PORT}"
PAGE_URL = f"http://localhost:{PAGE_PORT}"
sys.path.insert(0, str(ROOT))


def wait_for(url: str, seconds: int = 30) -> bool:
    for _ in range(seconds * 2):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pids_from_netstat(text: str, port: int) -> set[int]:
    """Windows 'netstat -ano' lines like:  TCP  0.0.0.0:8501  0.0.0.0:0  LISTENING  12345"""
    pids = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING" \
                and re.search(rf":{port}$", parts[1]):
            if parts[4].isdigit():
                pids.add(int(parts[4]))
    return pids


def image_from_tasklist(text: str) -> str:
    """'tasklist /FI "PID eq 123" /FO CSV /NH' gives: "python.exe","123",... -> python.exe"""
    m = re.match(r'\s*"([^"]+)"', text or "")
    return m.group(1).lower() if m else ""


def find_pids(port: int) -> set[int]:
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        return pids_from_netstat(out, port)
    out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    return {int(p) for p in out.split() if p.isdigit()}


def program_name(pid: int) -> str:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return image_from_tasklist(out)
    out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True).stdout
    return out.strip().lower()


def stop(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 15)


def free_port(port: int, what: str) -> bool:
    """Make sure nothing old is answering on this port. Returns False if we couldn't."""
    if not port_in_use(port):
        return True
    print(f"Port {port} is already in use, probably by an older copy of the {what} that is still running.")
    try:
        pids = find_pids(port)
    except (OSError, FileNotFoundError):
        pids = set()
    for pid in pids:
        name = program_name(pid)
        if "python" in name or "streamlit" in name or "uvicorn" in name:
            print(f"  Stopping the old copy (program {name}, number {pid})...")
            stop(pid)
        else:
            print(f"  Another program is using it ({name or 'unknown'}, number {pid}), so it was left alone.")
    for _ in range(20):
        if not port_in_use(port):
            print(f"  Port {port} is free now.")
            return True
        time.sleep(0.5)
    print(f"\nCouldn't free port {port}. Close every other PowerShell window that is running the app,\n"
          f"or restart the computer, then run this again.")
    return False


def main() -> int:
    from app import config
    from ui.logic import UI_VERSION

    if not (free_port(API_PORT, "API") and free_port(PAGE_PORT, "page")):
        return 1

    print(f"Starting the API (version {config.APP_VERSION}) on", API_URL, "...")
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)], cwd=ROOT)
    try:
        if not wait_for(f"{API_URL}/health"):
            print("The API didn't start. Look at the messages above for the reason.")
            return 1
        running = httpx.get(f"{API_URL}/health", timeout=5).json().get("version")
        if api.poll() is not None or running != config.APP_VERSION:
            print(f"Something else answered on port {API_PORT} (version {running}, expected {config.APP_VERSION}).\n"
                  "Close other app windows and run this again.")
            return 1
        print("API is running. Starting the page...")
        # headless = Streamlit doesn't ask setup questions; we open the browser ourselves.
        page = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "streamlit_app.py"),
                                 "--server.headless", "true", "--server.port", str(PAGE_PORT),
                                 "--browser.gatherUsageStats", "false"], cwd=ROOT)
        if wait_for(f"{PAGE_URL}/_stcore/health") and page.poll() is None:
            print(f"\nThe app is ready: {PAGE_URL}  (page version {UI_VERSION}, opening it in your browser)\n"
                  f"If you see an older page, press Ctrl + F5 in the browser.\nPress Ctrl + C here to stop.\n")
            webbrowser.open(PAGE_URL)
        else:
            print("The page didn't start. Look at the messages above for the reason.")
            page.terminate()
            return 1
        try:
            return page.wait()
        finally:
            page.terminate()
    except KeyboardInterrupt:
        return 0
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
        print("Stopped the API and the page.")


if __name__ == "__main__":
    sys.exit(main())
