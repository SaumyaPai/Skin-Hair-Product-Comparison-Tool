"""0.8.2: the start command stops an old copy of the app that's still running, so you never see an old page.
Run:  python -m pytest -q tests/test_launcher.py"""
import shutil
import socket
import subprocess
import sys
import time

import pytest

from app import config
from scripts import run_app
from ui.logic import UI_VERSION

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8501           0.0.0.0:0              LISTENING       4242
  TCP    [::]:8501              [::]:0                 LISTENING       4242
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       777
  TCP    127.0.0.1:18501        0.0.0.0:0              LISTENING       999
  TCP    127.0.0.1:52000        127.0.0.1:8501         ESTABLISHED     1234
"""


def test_finds_the_program_listening_on_a_port_in_windows_netstat():
    assert run_app.pids_from_netstat(NETSTAT, 8501) == {4242}          # not 18501, not the browser's connection
    assert run_app.pids_from_netstat(NETSTAT, 8000) == {777}
    assert run_app.pids_from_netstat(NETSTAT, 9999) == set()


def test_reads_the_program_name_from_windows_tasklist():
    assert run_app.image_from_tasklist('"python.exe","4242","Console","1","85,000 K"\n') == "python.exe"
    assert run_app.image_from_tasklist("INFO: No tasks are running which match the specified criteria.") == ""


def test_other_programs_are_never_stopped(monkeypatch, capsys):
    stopped = []
    monkeypatch.setattr(run_app, "port_in_use", lambda port: True)
    monkeypatch.setattr(run_app, "find_pids", lambda port: {55})
    monkeypatch.setattr(run_app, "program_name", lambda pid: "skype.exe")
    monkeypatch.setattr(run_app, "stop", stopped.append)
    monkeypatch.setattr(run_app.time, "sleep", lambda s: None)
    assert run_app.free_port(8501, "page") is False
    assert stopped == [] and "left alone" in capsys.readouterr().out


def test_old_python_copy_is_stopped(monkeypatch):
    state = {"busy": True}
    monkeypatch.setattr(run_app, "port_in_use", lambda port: state["busy"])
    monkeypatch.setattr(run_app, "find_pids", lambda port: {4242})
    monkeypatch.setattr(run_app, "program_name", lambda pid: "python.exe")
    monkeypatch.setattr(run_app, "stop", lambda pid: state.update(busy=False))
    assert run_app.free_port(8501, "page") is True and state["busy"] is False


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("lsof"), reason="needs lsof (Mac/Linux)")
def test_really_stops_a_running_python_server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    old = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if run_app.port_in_use(port):
                break
            time.sleep(0.1)
        assert run_app.port_in_use(port)
        assert run_app.free_port(port, "page") is True
        assert old.wait(timeout=10) is not None
    finally:
        if old.poll() is None:
            old.kill()


def test_page_and_api_versions_match():
    assert UI_VERSION == config.APP_VERSION
