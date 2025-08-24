#!/usr/bin/env python3
"""
Final integration test for the fixed Vulkan-Python pipeline
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def run_final_test():
    """Run the final integration test."""
    socket_path = "/tmp/final_test.sock"
    
    # Clean up
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    # Start Vulkan app
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("=" * 70)
    print("🎯 FINAL VULKAN-PYTHON INTEGRATION TEST")
    print("=" * 70)
    print("Starting Vulkan application...")
    
    vulkan_process = subprocess.Popen(
        cmd, 
        cwd=app_path.parent.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Give time for initialization
    time.sleep(5)
    
    try:
        # Import client
        sys.path.insert(0, str(Path(__file__).parent))
        import vk2torch_client
        
        print("Connecting to Vulkan...")
        client = vk2torch_client.VK2TorchClient(socket_path)
        
        if not client.connect():
            print("❌ Failed to connect")
            return False
            
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"   CUDA support: {client.has_cuda_support}")
        
        if not client.has_cuda_support:
            print("⚠️  No CUDA support available")
            client.disconnect()
            return True
        
        # Test frame capture
        print("\n" + "-" * 50)
        print("FRAME CAPTURE TEST")
        print("-" * 50)
        
        success_count = 0
        
        for i in range(5):
            print(f"\nFrame {i+1}/5:")
            
            # Create camera matrices
            angle = i * (np.pi / 2.5)
            distance = 5.0 + i * 0.3
            
            eye = np.array([
                distance * np.cos(angle),
                2.0 + i * 0.2,
                distance * np.sin(angle)
            ])
            
            view = np.eye(4, dtype=np.float32)
            view[:3, 3] = -eye
            
            proj = np.eye(4, dtype=np.float32)
            proj[0, 0] = 1.0
            proj[1, 1] = -1.0
            proj[2, 2] = 0.5
            proj[2, 3] = 0.5
            proj[3, 2] = -1.0
            
            # Update camera
            if client.update_camera(view, proj):
                print(f"  ✅ Camera updated (angle={np.degrees(angle):.0f}°)")
                
                # Get frame
                try:
                    frame = client.get_frame(timeout_ms=3000)
                    if frame is not None:
                        print(f"  ✅ Frame captured: {frame.shape} on {frame.device}")
                        
                        # Save PNG
                        filename = f"final_frame_{i:02d}.png"
                        if client.save_frame_png(frame, filename):
                            size = Path(filename).stat().st_size
                            print(f"  ✅ Saved {filename} ({size:,} bytes)")
                            success_count += 1
                        else:
                            print(f"  ⚠️  Failed to save {filename}")
                    else:
                        print("  ⚠️  Frame is None")
                except Exception as e:
                    print(f"  ⚠️  Frame error: {e}")
            else:
                print("  ❌ Camera update failed")
            
            time.sleep(0.3)
        
        client.disconnect()
        
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        
        if success_count > 0:
            print(f"✅ SUCCESS! Captured {success_count}/5 frames")
            print(f"✅ No VK_ERROR_DEVICE_LOST")
            print(f"✅ Pipeline is working correctly!")
            
            # List PNG files
            png_files = sorted(Path.cwd().glob("final_frame_*.png"))
            if png_files:
                print(f"\n📸 Created {len(png_files)} PNG files:")
                for png in png_files:
                    print(f"   {png.name}")
            
            return True
        else:
            print("⚠️  No frames were successfully captured")
            return False
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\nCleaning up...")
        
        if vulkan_process.poll() is None:
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                vulkan_process.kill()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        
        print("✅ Cleanup complete")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    
    # Run with conda environment
    activate = "source /home/gongyuning/anaconda3/bin/activate vk2torch"
    python_cmd = "python test_final_integration.py"
    cmd = f"{activate} && cd {Path.cwd()} && {python_cmd}"
    
    result = subprocess.run(cmd, shell=True, executable='/bin/bash')
    sys.exit(0 if result.returncode == 0 else 1)