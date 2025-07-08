#!/usr/bin/env python3
"""
setup_tunnel.py - Setup Cloudflare Tunnel configuration
"""

import subprocess
import sys
import os
import json

def run_command(cmd, description):
    """Run a command and return success status"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            print(f"✅ {description} successful")
            if result.stdout.strip():
                print(result.stdout)
            return True
        else:
            print(f"❌ {description} failed:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Error during {description}: {e}")
        return False

def check_login():
    """Check if user is logged in to Cloudflare"""
    try:
        result = subprocess.run(["cloudflared", "tunnel", "list"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Cloudflare authentication OK")
            return True
        else:
            print("❌ Not logged in to Cloudflare")
            print("💡 Please run: cloudflared tunnel login")
            return False
    except Exception as e:
        print(f"❌ Error checking login: {e}")
        return False

def create_tunnel(tunnel_name):
    """Create a new tunnel"""
    return run_command(
        f"cloudflared tunnel create {tunnel_name}",
        f"Creating tunnel '{tunnel_name}'"
    )

def create_config_file(tunnel_name, hostname, local_port=5000):
    """Create tunnel configuration file"""
    config_dir = os.path.expanduser("~/.cloudflared")
    config_path = os.path.join(config_dir, "config.yml")
    
    # Get tunnel ID
    try:
        result = subprocess.run(["cloudflared", "tunnel", "list"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            tunnel_id = None
            for line in lines:
                if tunnel_name in line:
                    tunnel_id = line.split()[0]
                    break
            
            if not tunnel_id:
                print(f"❌ Tunnel ID not found for {tunnel_name}")
                return False
                
            print(f"🔍 Found tunnel ID: {tunnel_id}")
        else:
            print("❌ Failed to get tunnel list")
            return False
    except Exception as e:
        print(f"❌ Error getting tunnel ID: {e}")
        return False
    
    # Create config content
    config_content = f"""tunnel: {tunnel_id}
credentials-file: {config_dir}/{tunnel_id}.json

ingress:
  - hostname: {hostname}
    service: http://localhost:{local_port}
  - service: http_status:404
"""
    
    try:
        os.makedirs(config_dir, exist_ok=True)
        with open(config_path, 'w') as f:
            f.write(config_content)
        print(f"✅ Created config file: {config_path}")
        print("📋 Configuration:")
        print(config_content)
        return True
    except Exception as e:
        print(f"❌ Error creating config file: {e}")
        return False

def setup_dns(tunnel_name, hostname):
    """Setup DNS routing for tunnel"""
    return run_command(
        f"cloudflared tunnel route dns {tunnel_name} {hostname}",
        f"Setting up DNS for {hostname}"
    )

def test_tunnel(tunnel_name):
    """Test tunnel connectivity"""
    return run_command(
        f"cloudflared tunnel run {tunnel_name} --dry-run",
        f"Testing tunnel '{tunnel_name}'"
    )

def main():
    print("🏠 Cloudflare Tunnel Setup for Smart Room")
    print("=" * 50)
    
    # Configuration
    tunnel_name = "smartroom"
    hostname = "smartroom.withink.pro"
    local_port = 5000
    
    print(f"Tunnel Name: {tunnel_name}")
    print(f"Hostname: {hostname}")
    print(f"Local Port: {local_port}")
    print("-" * 30)
    
    # Step 1: Check login
    if not check_login():
        print("\n💡 Setup Instructions:")
        print("1. Run: cloudflared tunnel login")
        print("2. Follow the browser login process")
        print("3. Run this script again")
        return
    
    # Step 2: Create tunnel (if needed)
    print("\n🔧 Step 1: Creating tunnel...")
    if not create_tunnel(tunnel_name):
        print("ℹ️  Tunnel might already exist, continuing...")
    
    # Step 3: Create config file
    print("\n🔧 Step 2: Creating configuration...")
    if not create_config_file(tunnel_name, hostname, local_port):
        print("❌ Failed to create configuration")
        return
    
    # Step 4: Setup DNS
    print("\n🔧 Step 3: Setting up DNS...")
    if not setup_dns(tunnel_name, hostname):
        print("ℹ️  DNS might already be configured, continuing...")
    
    # Step 5: Test configuration
    print("\n🔧 Step 4: Testing configuration...")
    if test_tunnel(tunnel_name):
        print("✅ Tunnel configuration is valid!")
    else:
        print("⚠️  Tunnel test failed, but configuration might still work")
    
    print("\n🎉 Setup Complete!")
    print("=" * 30)
    print("✅ Tunnel is configured and ready to use")
    print(f"🌐 Public URL: https://{hostname}")
    print(f"📍 Local URL: http://localhost:{local_port}")
    print("\n💡 Next steps:")
    print("1. Start your Flask app on port 5000")
    print("2. Run: python main.py")
    print("3. Access your app at the public URL")
    
    # Show current tunnel status
    print("\n📋 Current tunnel status:")
    run_command(f"cloudflared tunnel info {tunnel_name}", "Getting tunnel info")

if __name__ == "__main__":
    main()