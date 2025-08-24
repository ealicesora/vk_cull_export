#!/usr/bin/env python3
"""
Comprehensive debug test for Vulkan-Python integration
This will help identify exactly where issues occur
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def run_vulkan_debug_test():
    """Run a detailed debug test."""
    socket_path = "/tmp/debug_vulkan.sock"
    
    # Clean up any existing socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    # Start Vulkan app with more verbose output
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1",
        "--verbose"  # If supported
    ]
    
    print("=" * 70)
    print("VULKAN-PYTHON INTEGRATION DEBUG TEST")
    print("=" * 70)
    print(f"Starting Vulkan: {' '.join(cmd)}")
    print()
    
    # Start Vulkan with output visible
    vulkan_process = subprocess.Popen(
        cmd, 
        cwd=app_path.parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    
    print("Waiting for Vulkan to initialize...")
    
    # Monitor Vulkan output
    vulkan_ready = False
    start_time = time.time()
    while time.time() - start_time < 10:
        line = vulkan_process.stdout.readline()
        if line:
            print(f"[VULKAN] {line.rstrip()}")
            if "UDS server listening" in line:
                vulkan_ready = True
                break
            if "External Memory Manager initialized" in line:
                vulkan_ready = True
                break
    
    if not vulkan_ready:
        print("❌ Vulkan failed to initialize properly")
        vulkan_process.terminate()
        return False
    
    print("\n✅ Vulkan initialized, waiting for scene to load...")
    time.sleep(3)
    
    # Now test Python connection
    print("\n" + "=" * 70)
    print("PYTHON CLIENT TEST")
    print("=" * 70)
    
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import vk2torch_client
        
        print("Creating client...")
        client = vk2torch_client.VK2TorchClient(socket_path)
        
        print("Attempting connection...")
        if not client.connect():
            print("❌ Failed to connect to Vulkan")
            return False
            
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"   Format: {client.format}")
        print(f"   CUDA support: {client.has_cuda_support}")
        print(f"   Camera buffer: {client.cam_bytes} bytes")
        print(f"   Color buffer: {client.color_readback_bytes} bytes")
        
        if not client.has_cuda_support:
            print("⚠️  No CUDA support - limited functionality")
            client.disconnect()
            return True
        
        # Test semaphore synchronization
        print("\n" + "-" * 50)
        print("SEMAPHORE TEST")
        print("-" * 50)
        
        # Signal a test value
        print("Testing semaphore echo...")
        # This would need to be implemented in the client
        
        # Test camera updates
        print("\n" + "-" * 50)
        print("CAMERA UPDATE TEST")
        print("-" * 50)
        
        for i in range(2):
            print(f"\nFrame {i+1}:")
            
            # Create simple matrices
            view = np.eye(4, dtype=np.float32)
            proj = np.eye(4, dtype=np.float32)
            
            print("  Updating camera...")
            if client.update_camera(view, proj):
                print("  ✅ Camera updated successfully")
            else:
                print("  ❌ Camera update failed")
                break
            
            # Try to get frame with detailed error handling
            print("  Waiting for frame...")
            try:
                frame = client.get_frame(timeout_ms=2000)
                if frame is not None:
                    print(f"  ✅ Frame received: {frame.shape} {frame.dtype}")
                    print(f"     Device: {frame.device}")
                    
                    # Save frame
                    filename = f"debug_frame_{i:02d}.png"
                    if client.save_frame_png(frame, filename):
                        size = Path(filename).stat().st_size
                        print(f"  ✅ Saved {filename} ({size:,} bytes)")
                else:
                    print("  ⚠️  Frame is None (timeout or error)")
            except TimeoutError:
                print("  ⚠️  Frame timeout")
            except Exception as e:
                print(f"  ❌ Frame error: {type(e).__name__}: {e}")
            
            time.sleep(0.5)
        
        client.disconnect()
        print("\n✅ Client test completed")
        return True
        
    except Exception as e:
        print(f"\n❌ Client error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\n" + "=" * 70)
        print("CLEANUP")
        print("=" * 70)
        
        # Check Vulkan status
        if vulkan_process.poll() is None:
            print("Vulkan still running, terminating...")
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=3)
                print("✅ Vulkan terminated")
            except subprocess.TimeoutExpired:
                vulkan_process.kill()
                print("✅ Vulkan killed")
        else:
            print(f"Vulkan already exited with code: {vulkan_process.returncode}")
            
        # Clean up socket
        if os.path.exists(socket_path):
            os.unlink(socket_path)
            print("✅ Socket cleaned up")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    
    # Run in conda environment
    activate = "source /home/gongyuning/anaconda3/bin/activate vk2torch"
    python_cmd = "python -c 'from test_debug_vulkan import run_vulkan_debug_test; run_vulkan_debug_test()'"
    cmd = f"{activate} && {python_cmd}"
    
    result = subprocess.run(cmd, shell=True, executable='/bin/bash')
    sys.exit(0 if result.returncode == 0 else 1)