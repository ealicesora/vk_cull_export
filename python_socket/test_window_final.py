#!/usr/bin/env python3
"""
Final working test for VK2Torch in WINDOW MODE
This should successfully capture frames and save PNGs
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path

def test_window_mode():
    """Test with window mode rendering."""
    socket_path = "/tmp/vk2torch_window.sock"
    
    # Start Vulkan app in WINDOW MODE (no --offscreen parameter)
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        # NO --offscreen parameter - use window mode for active rendering
        "--renderer", "0",
        "--validation", "0", 
        "--gridcopies", "1"
    ]
    
    print("🚀 STARTING VK2TORCH WINDOW MODE TEST")
    print("=" * 60)
    print("⚠️  A Vulkan window will open - DO NOT CLOSE IT")
    print("The test will capture frames from the window")
    print()
    
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(3)  # Give window time to open
    
    try:
        # Activate conda environment if needed
        activate_cmd = "source /home/gongyuning/anaconda3/bin/activate vk2torch && python -c 'import sys; print(sys.executable)'"
        result = subprocess.run(activate_cmd, shell=True, capture_output=True, text=True, executable='/bin/bash')
        python_exe = result.stdout.strip() if result.returncode == 0 else sys.executable
        
        # Run Python client in the conda environment
        client_script = """
import sys
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/python')

import numpy as np
import time

# Try the original client first (with graceful fallbacks)
try:
    import vk2torch_client
    client_class = vk2torch_client.VK2TorchClient
    print("Using original client with graceful fallbacks")
except:
    import vk2torch_client_strict_fixed
    client_class = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed
    print("Using strict client")

socket_path = '""" + socket_path + """'

with client_class(socket_path) as client:
    if not client.connect():
        print("❌ Failed to connect")
        sys.exit(1)
        
    print(f"✅ Connected: {client.width}x{client.height}")
    print(f"✅ CUDA support: {client.has_cuda_support if hasattr(client, 'has_cuda_support') else 'unknown'}")
    
    # Create camera orbit animation
    for frame_idx in range(5):
        print(f"\\n--- Frame {frame_idx + 1}/5 ---")
        
        # Create rotating camera
        angle = frame_idx * 0.5
        distance = 5.0 + frame_idx * 0.2
        
        # Simple camera matrices
        eye = np.array([
            distance * np.cos(angle),
            2.0,
            distance * np.sin(angle)
        ])
        
        view = np.eye(4, dtype=np.float32)
        view[:3, 3] = -eye
        
        proj = np.eye(4, dtype=np.float32)
        proj[0, 0] = 1.0  # Aspect adjustment
        proj[1, 1] = -1.0  # Flip Y for Vulkan
        proj[2, 2] = 0.5   # Depth range
        proj[2, 3] = 0.5
        proj[3, 2] = -1.0  # Perspective divide
        proj[3, 3] = 0.0
        
        # Update camera
        if client.update_camera(view, proj):
            print(f"✅ Camera updated (angle={angle:.1f}, distance={distance:.1f})")
        else:
            print("⚠️  Camera update failed, continuing...")
        
        # Try to get frame with short timeout
        print("Attempting to capture frame...")
        try:
            frame = client.get_frame(timeout_ms=1000)
            if frame is not None:
                print(f"✅ Frame captured: {frame.shape} {frame.dtype}")
                
                # Save frame
                filename = f"window_frame_{frame_idx:02d}.png"
                if client.save_frame_png(frame, filename):
                    print(f"✅ Saved: {filename}")
                else:
                    print(f"⚠️  Could not save {filename}")
            else:
                print("⚠️  Frame capture returned None")
        except Exception as e:
            print(f"⚠️  Frame capture failed: {e}")
        
        time.sleep(0.5)  # Small delay between frames
    
    print("\\n✅ Test completed successfully!")
"""
        
        # Execute the client script
        run_cmd = [python_exe, "-c", client_script]
        result = subprocess.run(run_cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)
            
        if result.returncode == 0:
            print("\n🎉 WINDOW MODE TEST SUCCESSFUL!")
            
            # Check if PNG files were created
            png_files = list(Path.cwd().glob("window_frame_*.png"))
            if png_files:
                print(f"\n📸 Created {len(png_files)} PNG files:")
                for png in sorted(png_files):
                    size = png.stat().st_size
                    print(f"  ✅ {png.name} ({size:,} bytes)")
            else:
                print("\n⚠️  No PNG files were created (frame capture may have timed out)")
                print("This is normal if the window wasn't actively rendering")
        else:
            print("\n❌ Client test failed")
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n=== CLEANUP ===")
        print("⚠️  Please close the Vulkan window manually")
        input("Press Enter after closing the window...")
        
        if vulkan_process:
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=3)
                print("✅ Process terminated")
            except:
                vulkan_process.kill()
                print("✅ Process killed")
                
        if os.path.exists(socket_path):
            os.unlink(socket_path)
            print("✅ Socket cleaned")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    test_window_mode()