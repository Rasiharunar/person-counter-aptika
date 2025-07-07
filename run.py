#!/usr/bin/env python3
"""
Script untuk menjalankan Flask app dengan ngrok
"""
import subprocess
import sys
import os
import time
import threading
import signal

def install_requirements():
    """Install requirements jika belum ada"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Requirements installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing requirements: {e}")
        sys.exit(1)

def check_ngrok():
    """Check apakah ngrok sudah terinstall"""
    try:
        subprocess.check_call(["ngrok", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ ngrok is installed")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ngrok is not installed")
        print("Please install ngrok from https://ngrok.com/download")
        return False

def run_flask_app():
    """Run Flask app"""
    try:
        # Set environment variables
        os.environ['FLASK_ENV'] = 'production'
        os.environ['FLASK_DEBUG'] = '0'
        
        # Run Flask app
        subprocess.run([sys.executable, "app4.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running Flask app: {e}")
    except KeyboardInterrupt:
        print("\n🛑 Flask app stopped by user")

def run_ngrok():
    """Run ngrok tunnel"""
    try:
        print("🚀 Starting ngrok tunnel...")
        time.sleep(2)  # Wait for Flask to start
        subprocess.run(["ngrok", "http", "5000"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running ngrok: {e}")
    except KeyboardInterrupt:
        print("\n🛑 ngrok stopped by user")

def main():
    print("🏠 Smart Room Person Counter - ngrok Setup")
    print("=" * 50)
    
    # Check if ngrok is installed
    if not check_ngrok():
        return
    
    # Install requirements
    print("📦 Installing requirements...")
    install_requirements()
    
    # Create templates directory if it doesn't exist
    os.makedirs("templates", exist_ok=True)
    
    print("\n🎯 Setup complete! Now you can:")
    print("1. Run Flask app: python app.py")
    print("2. Run ngrok in another terminal: ngrok http 5000")
    print("3. Or run both automatically with this script")
    
    choice = input("\nDo you want to run Flask app and ngrok now? (y/n): ").lower()
    
    if choice == 'y':
        print("\n🚀 Starting services...")
        
        # Start Flask app in a separate thread
        flask_thread = threading.Thread(target=run_flask_app)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Start ngrok
        try:
            run_ngrok()
        except KeyboardInterrupt:
            print("\n🛑 Shutting down services...")
            
    print("\n✅ Setup completed!")

if __name__ == "__main__":
    main()