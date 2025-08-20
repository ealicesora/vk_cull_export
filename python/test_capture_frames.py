#!/usr/bin/env python3
"""
Simple frame capture test that saves PNG files
Uses the original client with graceful fallbacks
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def capture_frames():
    """Capture frames and save as PNG."""
    socket_path = "/tmp/vk2torch_capture.sock"
    
    # Start Vulkan app in window mode
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("🎬 VK2TORCH FRAME CAPTURE TEST")
    print("=" * 60)
    print("Starting Vulkan application...")
    print("A window will open - keep it visible for frame capture")
    print()
    
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent, 
                                     stdout=subprocess.DEVNULL, 
                                     stderr=subprocess.DEVNULL)
    time.sleep(5)  # Give more time for Vulkan app to start
    
    try:
        # Import the original client with fallbacks
        sys.path.insert(0, str(Path(__file__).parent))
        import vk2torch_client
        
        print("Connecting to Vulkan application...")
        client = vk2torch_client.VK2TorchClient(socket_path)
        
        if not client.connect():
            print("❌ Failed to connect")
            return False
            
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"✅ CUDA available: {client.has_cuda_support}")
        print()
        
        # Capture a few frames with different camera positions
        num_frames = 3
        captured = 0
        
        for i in range(num_frames):
            print(f"Capturing frame {i+1}/{num_frames}...")
            
            # Create simple camera movement
            angle = i * (2.0 * np.pi / num_frames)
            distance = 5.0
            height = 2.0
            
            # Camera position
            eye = np.array([
                distance * np.cos(angle),
                height,
                distance * np.sin(angle)
            ])
            
            # Simple view matrix (look at origin)
            view = np.eye(4, dtype=np.float32)
            view[:3, 3] = -eye
            
            # Simple projection matrix
            proj = np.eye(4, dtype=np.float32)
            proj[0, 0] = 1.0
            proj[1, 1] = -1.0  # Flip Y for Vulkan
            proj[2, 2] = 0.5
            proj[2, 3] = 0.5
            proj[3, 2] = -1.0
            
            # Update camera
            if client.update_camera(view, proj):
                print(f"  ✅ Camera position set (angle={np.degrees(angle):.0f}°)")
            
            # Try to capture frame
            try:
                frame = client.get_frame(timeout_ms=500)
                if frame is not None:
                    # Save as PNG
                    filename = f"captured_frame_{i:02d}.png"
                    if client.save_frame_png(frame, filename):
                        size = Path(filename).stat().st_size
                        print(f"  ✅ Saved {filename} ({size:,} bytes)")
                        captured += 1
                    else:
                        print(f"  ⚠️  Could not save {filename}")
                else:
                    print(f"  ⚠️  Frame capture timed out")
            except Exception as e:
                print(f"  ⚠️  Frame capture error: {e}")
            
            time.sleep(0.2)
        
        client.disconnect()
        
        print()
        print("=" * 60)
        if captured > 0:
            print(f"🎉 SUCCESS! Captured {captured}/{num_frames} frames")
            print()
            print("📸 PNG files created:")
            for png in sorted(Path.cwd().glob("captured_frame_*.png")):
                print(f"  ✅ {png.name}")
            return True
        else:
            print("⚠️  No frames were captured")
            print("This may happen if the window is not actively rendering")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print()
        print("Cleaning up...")
        
        if vulkan_process:
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=2)
            except:
                vulkan_process.kill()
                
        if os.path.exists(socket_path):
            os.unlink(socket_path)
            
        print("✅ Cleanup complete")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    
    # Activate conda environment and run
    activate_cmd = "source /home/gongyuning/anaconda3/bin/activate vk2torch"
    python_cmd = "python -c 'from test_capture_frames import capture_frames; capture_frames()'"
    full_cmd = f"{activate_cmd} && {python_cmd}"
    
    result = subprocess.run(full_cmd, shell=True, executable='/bin/bash')
    sys.exit(0 if result.returncode == 0 else 1)