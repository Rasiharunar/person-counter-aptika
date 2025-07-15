#!/usr/bin/env python3
"""
main.py — Jalankan Flask app
"""

import subprocess
import sys
import os
import signal

# Global variables
flask_process = None

def install_requirements():
    if os.path.exists("requirements.txt"):
        print("Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def run_flask():
    global flask_process
    if not os.path.exists("app1.py"):
        print("app1.py not found")
        return
    flask_process = subprocess.Popen([sys.executable, "app1.py"])

def cleanup():
    if flask_process:
        flask_process.terminate()

def main():
    signal.signal(signal.SIGINT, lambda s, f: cleanup() or sys.exit(0))

    install_requirements()
    run_flask()

    print("Running Flask on http://localhost:5000")

    try:
        while True:
            if flask_process.poll() is not None:
                print("Flask process terminated")
                break
            flask_process.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        cleanup()

if __name__ == "__main__":
    main()