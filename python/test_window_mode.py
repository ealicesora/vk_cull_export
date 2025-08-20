#!/usr/bin/env python3
"""
Test with window mode (not offscreen)
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def test_window_mode():
    """Test with window mode."""
    socket_path = "/tmp/test_window.sock"
    
    # Start Vulkan app WITHOUT --offscreen (window mode)
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        # NO --offscreen parameter
        "--renderer", "0", 
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("🔍 TESTING WINDOW MODE (NOT OFFSCREEN)")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(4)
    
    try:
        import vk2torch_client_strict_fixed
        
        print("\n=== TESTING WINDOW MODE ===")
        with vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path) as client:
            if client.connect():
                print("✅ Window mode client connected")
                print(f"✅ Has CUDA: {client.has_strict_cuda_support}")
                
                # Test camera update
                view = np.eye(4, dtype=np.float32)
                proj = np.eye(4, dtype=np.float32)
                
                if client.update_camera(view, proj):
                    print("✅ Window mode camera update OK")
                    
                    # Test frame capture
                    print("Trying get_frame in window mode...")
                    start_time = time.time()
                    frame = client.get_frame(timeout_ms=5000)
                    end_time = time.time()
                    
                    if frame is not None:
                        print(f"✅ Window mode get_frame SUCCESS in {(end_time-start_time)*1000:.1f}ms!")
                        print(f"✅ Frame: {frame.shape} on {frame.device}")
                        client.save_frame_png(frame, "window_mode_test.png")
                        print("✅ Frame saved")
                        return True
                    else:
                        print("❌ Window mode get_frame returned None")
                else:
                    print("❌ Window mode camera update failed")
            else:
                print("❌ Window mode client connection failed")
        
        return False
    
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\n⚠️  Remember to close the Vulkan window manually!")
        input("Press Enter after closing the window to continue cleanup...")
        
        if vulkan_process:
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    success = test_window_mode()
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)