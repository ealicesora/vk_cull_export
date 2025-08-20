#!/usr/bin/env python3
"""
Test only the connection without any frame operations
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def test_connection_only():
    """Test connection without frame operations."""
    socket_path = "/tmp/connection_only.sock"
    
    # Start Vulkan app
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--offscreen", "1",
        "--renderer", "0", 
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("🔍 TESTING CONNECTION ONLY (NO FRAME OPERATIONS)")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(3)
    
    try:
        import vk2torch_client_strict_fixed
        
        print("\n=== TESTING CONNECTION ESTABLISHMENT ===")
        client = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path)
        
        print("Step 1: Calling connect()...")
        success = client.connect()
        
        if success:
            print("✅ Connection established successfully!")
            print(f"✅ Frame dimensions: {client.width}x{client.height}")
            print(f"✅ CUDA support: {hasattr(client, 'has_strict_cuda_support') and client.has_strict_cuda_support}")
            print(f"✅ Connected status: {client.connected}")
            
            print("\n=== TESTING DISCONNECT ===")
            client.disconnect()
            print("✅ Disconnected successfully")
            
            return True
        else:
            print("❌ Connection failed")
            return False
    
    except Exception as e:
        print(f"❌ Exception during connection: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if vulkan_process:
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    success = test_connection_only()
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)