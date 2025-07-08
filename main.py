#!/usr/bin/env python3
"""
main.py — Jalankan Flask app & Cloudflare Tunnel secara bersamaan
"""

import subprocess
import sys
import os
import threading
import time

def install_requirements():
    """Install dependencies dari requirements.txt"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Requirements installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing requirements: {e}")
        sys.exit(1)

def run_cloudflared():
    """Jalankan Cloudflare Tunnel"""
    try:
        print("🌩️ Starting Cloudflare Tunnel...")
        subprocess.Popen(["cloudflared", "tunnel", "run", "smartroom"])
        time.sleep(5)  # Beri waktu 5 detik biar tunnel siap
    except Exception as e:
        print(f"❌ Error starting Cloudflare Tunnel: {e}")
        sys.exit(1)

def run_flask_app():
    """Jalankan Flask app"""
    try:
        os.environ['FLASK_ENV'] = 'production'
        os.environ['FLASK_DEBUG'] = '0'
        subprocess.run([sys.executable, "app4.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running Flask app: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Flask app stopped by user")

def main():
    print("🏠 Smart Room Person Counter - Launcher")
    print("=" * 50)

    print("📦 Installing requirements...")
    install_requirements()

    os.makedirs("templates", exist_ok=True)

    run_cloudflared()

    print("🚀 Running Flask App...")
    run_flask_app()

    print("\n✅ Flask app exited.")

if __name__ == "__main__":
    main()
