#!/usr/bin/env python3
"""
Test original client behavior
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def test_original_client():
    """Test original client."""
    socket_path = "/tmp/test_original.sock"
    
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
    
    print("🔍 TESTING ORIGINAL CLIENT")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(4)
    
    try:
        import vk2torch_client
        
        print("\n=== TESTING ORIGINAL CLIENT ===")
        with vk2torch_client.VK2TorchClient(socket_path) as client:
            if client.connect():
                print("✅ Original client connected")
                print(f"✅ Has CUDA: {client.has_cuda_support}")
                
                # Test camera update
                view = np.eye(4, dtype=np.float32)
                proj = np.eye(4, dtype=np.float32)
                
                if client.update_camera(view, proj):
                    print("✅ Original camera update OK")
                    
                    # Test frame capture
                    print("Trying get_frame...")
                    start_time = time.time()
                    frame = client.get_frame(timeout_ms=3000)
                    end_time = time.time()
                    
                    if frame is not None:
                        print(f"✅ Original get_frame SUCCESS in {(end_time-start_time)*1000:.1f}ms!")
                        print(f"✅ Frame: {frame.shape} on {frame.device if hasattr(frame, 'device') else 'CPU'}")
                        return True
                    else:
                        print("❌ Original get_frame returned None")
                else:
                    print("❌ Original camera update failed")
            else:
                print("❌ Original client connection failed")
        
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
    success = test_original_client()
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)