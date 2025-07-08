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
        # Pilih tunnel yang ingin digunakan
        tunnel_name = "smartroom"  # Ganti ke "smartroom2" jika perlu
        
        # Jalankan tunnel dan simpan prosesnya
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "run", tunnel_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print(f"🌩️ Cloudflare Tunnel '{tunnel_name}' started with PID: {process.pid}")
        
        # Monitor tunnel status
        time.sleep(3)
        if process.poll() is None:
            print("✅ Tunnel is running")
        else:
            print("❌ Tunnel failed to start")
            stdout, stderr = process.communicate()
            print(f"Error: {stderr}")
            
        return process
        
    except Exception as e:
        print(f"❌ Error starting Cloudflare Tunnel: {e}")
        return None

def run_flask_app():
    """Jalankan Flask app"""
    try:
        print("🚀 Starting Flask App...")
        os.environ['FLASK_ENV'] = 'production'
        os.environ['FLASK_DEBUG'] = '0'
        
        # Jalankan Flask app
        flask_process = subprocess.Popen([sys.executable, "app.py"])
        print(f"🚀 Flask app started with PID: {flask_process.pid}")
        
        return flask_process
        
    except Exception as e:
        print(f"❌ Error running Flask app: {e}")
        return None

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Shutting down services...")
    sys.exit(0)

def main():
    print("🏠 Smart Room Person Counter - Launcher")
    print("=" * 50)

    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    print("📦 Installing requirements...")
    install_requirements()

    # Create templates directory if it doesn't exist
    os.makedirs("templates", exist_ok=True)

    # Start Cloudflare Tunnel in background
    tunnel_process = run_cloudflared()
    
    # Give tunnel time to establish connection
    time.sleep(5)
    
    # Start Flask app
    flask_process = run_flask_app()
    
    if flask_process:
        try:
            print("\n🎉 Both services are running!")
            print("📱 Flask App: http://localhost:5000")
            print("🌐 Public URL: https://smartroom.withink.pro")
            print("Press Ctrl+C to stop both services")
            
            # Wait for Flask app to finish
            flask_process.wait()
            
        except KeyboardInterrupt:
            print("\n🛑 Stopping services...")
            
        finally:
            # Clean up processes
            if flask_process and flask_process.poll() is None:
                flask_process.terminate()
                print("✅ Flask app stopped")
                
            if tunnel_process and tunnel_process.poll() is None:
                tunnel_process.terminate()
                print("✅ Cloudflare Tunnel stopped")
    
    print("\n✅ All services stopped.")

if __name__ == "__main__":
    main()