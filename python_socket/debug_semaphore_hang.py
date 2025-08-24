#!/usr/bin/env python3
"""
Debug the semaphore hang issue
"""

import os
import sys
import subprocess
import time
import threading
from pathlib import Path

def test_semaphore_hang():
    """Debug semaphore hang issue."""
    socket_path = "/tmp/debug_hang.sock"
    
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
    
    print("🔍 DEBUGGING SEMAPHORE HANG ISSUE")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent, 
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(3)
    
    try:
        import vk2torch_client_strict_fixed
        import numpy as np
        
        print("\n=== TESTING WITH DETAILED DEBUGGING ===")
        client = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path)
        
        if client.connect():
            print("✅ Connection successful")
            print(f"✅ Frame counter starts at: {client.frame_number}")
            
            # Test camera update first
            print("\n=== STEP 1: UPDATE CAMERA ===")
            view_matrix = np.eye(4, dtype=np.float32)
            proj_matrix = np.eye(4, dtype=np.float32)
            
            print("Calling update_camera...")
            success = client.update_camera(view_matrix, proj_matrix)
            print(f"Camera update result: {success}")
            
            if success:
                print(f"Frame number after camera update: {client.frame_number}")
                print("\n=== STEP 2: GET FRAME (WITH TIMEOUT) ===")
                print("Calling get_frame with 2 second timeout...")
                
                # Add timeout mechanism
                def timeout_handler():
                    print("❌ TIMEOUT: get_frame call hanging for >5 seconds")
                    print("This suggests Vulkan is not signaling frameDone semaphore")
                    
                timer = threading.Timer(5.0, timeout_handler)
                timer.start()
                
                try:
                    start_time = time.time()
                    frame = client.get_frame(timeout_ms=2000)
                    end_time = time.time()
                    timer.cancel()
                    
                    if frame is not None:
                        print(f"✅ SUCCESS: Frame captured in {(end_time-start_time)*1000:.1f}ms")
                        print(f"✅ Frame shape: {frame.shape}")
                        print(f"✅ Frame device: {frame.device}")
                    else:
                        print("❌ get_frame returned None")
                        
                except Exception as e:
                    timer.cancel()
                    print(f"❌ EXCEPTION in get_frame: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("❌ Camera update failed - cannot proceed")
        else:
            print("❌ Connection failed")
    
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Check Vulkan process output
        print("\n=== VULKAN PROCESS OUTPUT ===")
        try:
            stdout, stderr = vulkan_process.communicate(timeout=2)
            print("STDOUT:", stdout[-1000:] if stdout else "No stdout")
            print("STDERR:", stderr[-1000:] if stderr else "No stderr")
        except subprocess.TimeoutExpired:
            print("Vulkan process still running")
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)
    
    return False

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    test_semaphore_hang()