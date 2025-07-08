#!/usr/bin/env python3
"""
main.py — Jalankan Flask app & Cloudflare Tunnel secara bersamaan
"""

import subprocess
import sys
import os
import threading
import time
import signal
import json
import requests

# Global variables
flask_process = None
tunnel_process = None

def install_requirements():
    if os.path.exists("requirements.txt"):
        print("Installing requirements...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def check_cloudflared():
    try:
        subprocess.run(["cloudflared", "--version"], check=True, stdout=subprocess.DEVNULL)
        return True
    except:
        return False

def check_login():
    return os.path.exists(os.path.expanduser("~/.cloudflared/cert.pem"))

def tunnel_exists(name):
    result = subprocess.run(["cloudflared", "tunnel", "list"], capture_output=True, text=True)
    return name in result.stdout

def get_tunnel_id(name):
    result = subprocess.run(["cloudflared", "tunnel", "list"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if name in line:
            return line.split()[0]
    return None

def create_tunnel_config(tunnel_name, hostname):
    tunnel_id = get_tunnel_id(tunnel_name)
    config_path = os.path.expanduser("~/.cloudflared/config.yml")
    content = f"""tunnel: {tunnel_id}
credentials-file: C:\\Users\\{os.getenv('USERNAME')}\\.cloudflared\\{tunnel_id}.json

ingress:
  - hostname: {hostname}
    service: http://localhost:5000
  - service: http_status:404
"""
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w') as f:
        f.write(content)

def setup_tunnel():
    tunnel_name = "person-counter"
    hostname = "personcounter.withink.pro"

    if not check_cloudflared():
        print("Cloudflared not installed.")
        return False

    if not check_login():
        subprocess.run(["cloudflared", "tunnel", "login"])

    if not tunnel_exists(tunnel_name):
        subprocess.run(["cloudflared", "tunnel", "create", tunnel_name])

    subprocess.run(["cloudflared", "tunnel", "route", "dns", tunnel_name, hostname])
    create_tunnel_config(tunnel_name, hostname)
    return True

def run_flask():
    global flask_process
    if not os.path.exists("app.py"):
        print("app.py not found")
        return
    flask_process = subprocess.Popen([sys.executable, "app.py"])

def run_tunnel():
    global tunnel_process
    tunnel_process = subprocess.Popen(["cloudflared", "tunnel", "run", "person-counter"])

def cleanup():
    if flask_process:
        flask_process.terminate()
    if tunnel_process:
        tunnel_process.terminate()

def main():
    signal.signal(signal.SIGINT, lambda s, f: cleanup() or sys.exit(0))

    install_requirements()
    setup_tunnel()

    run_flask()
    time.sleep(3)
    run_tunnel()

    print("Running Flask on http://localhost:5000")
    print("Public URL: https://personcounter.withink.pro")

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
