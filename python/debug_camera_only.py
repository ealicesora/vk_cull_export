#!/usr/bin/env python3
"""
Test camera update only without frame capture
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def test_camera_only():
    """Test camera update without frame capture."""
    socket_path = "/tmp/camera_only.sock"
    
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
    
    print("🔍 TESTING CAMERA UPDATE ONLY")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(3)
    
    try:
        import vk2torch_client_strict_fixed
        
        print("\n=== TESTING CAMERA UPDATE ===")
        client = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path)
        
        if client.connect():
            print("✅ Connection successful")
            
            # Test camera update
            print("Preparing camera matrices...")
            view_matrix = np.eye(4, dtype=np.float32)
            proj_matrix = np.eye(4, dtype=np.float32)
            
            print("Calling update_camera...")
            start_time = time.time()
            success = client.update_camera(view_matrix, proj_matrix)
            end_time = time.time()
            
            if success:
                print(f"✅ Camera update successful in {(end_time-start_time)*1000:.1f}ms")
                print(f"✅ Frame number: {client.frame_number}")
                
                # Wait a bit and disconnect
                time.sleep(1)
                print("✅ Test completed - disconnecting")
                client.disconnect()
                return True
            else:
                print("❌ Camera update failed")
                return False
        else:
            print("❌ Connection failed")
            return False
    
    except Exception as e:
        print(f"❌ Exception: {e}")
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
    success = test_camera_only()
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)