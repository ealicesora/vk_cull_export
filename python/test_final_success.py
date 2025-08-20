#!/usr/bin/env python3
"""
Quick success test of the fixed strict client
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def test_success():
    """Quick success test."""
    socket_path = "/tmp/success_test.sock"
    
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
    
    print("🧪 TESTING FIXED STRICT CLIENT")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(2)
    
    try:
        import vk2torch_client_strict_fixed
        
        with vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path) as client:
            print("✅ Client created")
            
            if client.connect():
                print("✅ Connection successful")
                print(f"✅ Frame dimensions: {client.width}x{client.height}")
                print(f"✅ CUDA support: {client.has_strict_cuda_support}")
                
                if client.has_strict_cuda_support:
                    print("🎉 ALL CORE FUNCTIONALITY WORKING!")
                    
                    # Test one frame capture
                    import numpy as np
                    view = np.eye(4, dtype=np.float32)
                    proj = np.eye(4, dtype=np.float32)
                    
                    client.update_camera(view, proj)
                    print("✅ Camera update successful")
                    
                    frame = client.get_frame(timeout_ms=1000)
                    print(f"✅ Frame captured: {frame.shape} {frame.dtype} on {frame.device}")
                    
                    # Save frame
                    client.save_frame_png(frame, "success_test.png")
                    print("✅ Frame saved successfully")
                    
                    print("\n🎉 STRICT CUDA V1 CLIENT: COMPLETE SUCCESS! 🎉")
                    return True
            else:
                print("❌ Connection failed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if vulkan_process:
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)
    
    return False

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    success = test_success()
    sys.exit(0 if success else 1)