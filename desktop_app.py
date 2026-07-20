"""Desktop launcher for Machine Audit Bot.

Starts the Streamlit server in the background and opens it in a
native desktop window (via pywebview), so the app runs like a
standalone program instead of a browser tab.
"""
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

BASE_DIR = Path(__file__).parent
APP_PATH = BASE_DIR / "app.py"
PORT = 8501
URL = f"http://localhost:{PORT}"


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("localhost", port)) == 0


def start_streamlit() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(PORT):
            return True
        time.sleep(0.3)
    return False


def main() -> None:
    server_process = start_streamlit()

    if not wait_for_server():
        server_process.terminate()
        raise RuntimeError("Streamlit server did not start in time")

    window = webview.create_window(
        "Machine Audit Bot",
        URL,
        width=1400,
        height=900,
        min_size=(900, 600),
    )

    try:
        webview.start()
    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()


if __name__ == "__main__":
    main()
