#!/usr/bin/env python3
"""
Complete VK2Torch Test Script
This will test the full pipeline and save PNG files
"""

import os
import sys
import subprocess
import time
import signal
from pathlib import Path

def run_complete_test():
    """Run the complete VK2Torch test."""
    
    # Configuration
    socket_path = "/tmp/vk2torch_test.sock"
    vulkan_app = Path(__file__).parent / "_bin/Release/vk_lod_clusters"
    python_dir = Path(__file__).parent / "python"
    
    # Clean up any existing processes and sockets
    print("🧹 Cleaning up...")
    subprocess.run(["pkill", "-f", "vk_lod_clusters"], stderr=subprocess.DEVNULL)
    time.sleep(1)
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    print("\n" + "="*70)
    print("🎯 VK2TORCH COMPLETE TEST")
    print("="*70)
    
    # Step 1: Start Vulkan application
    print("\n📌 Step 1: Starting Vulkan application...")
    vulkan_cmd = [
        str(vulkan_app),
        "--uds", socket_path,
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print(f"Command: {' '.join(vulkan_cmd)}")
    vulkan_process = subprocess.Popen(
        vulkan_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Wait for Vulkan to initialize
    print("⏳ Waiting for Vulkan to initialize...")
    initialized = False
    start_time = time.time()
    
    while time.time() - start_time < 15:
        line = vulkan_process.stdout.readline()
        if line:
            print(f"[VULKAN] {line.rstrip()}")
            if "External Memory Manager initialized successfully" in line:
                initialized = True
                break
            if "Scene::saveCache saved" in line:
                # Scene is loaded
                print("✅ Scene loaded")
                initialized = True
                break
    
    if not initialized:
        print("❌ Vulkan failed to initialize")
        vulkan_process.terminate()
        return False
    
    print("✅ Vulkan initialized successfully")
    time.sleep(2)  # Give it a moment to stabilize
    
    # Step 2: Run Python client test
    print("\n📌 Step 2: Running Python client test...")
    
    test_script = f"""
import sys
import time
import numpy as np
from pathlib import Path

# Add Python module path
sys.path.insert(0, '{python_dir}')

# Import the client
import vk2torch_client

print("\\n🔌 Connecting to Vulkan...")
client = vk2torch_client.VK2TorchClient('{socket_path}')

if not client.connect():
    print("❌ Failed to connect")
    sys.exit(1)

print(f"✅ Connected: {{client.width}}x{{client.height}}")
print(f"   Format: {{client.format}}")
print(f"   CUDA support: {{client.has_cuda_support}}")

if not client.has_cuda_support:
    print("⚠️  No CUDA support - will try to continue anyway")

# Wait a moment for synchronization
time.sleep(1)

print("\\n📸 Capturing frames...")
success_count = 0

for i in range(5):
    print(f"\\n--- Frame {{i+1}}/5 ---")
    
    # Create camera matrices with different angles
    angle = i * (np.pi / 3)  # 60 degree increments
    distance = 5.0 + i * 0.5
    height = 2.0 + i * 0.3
    
    # Simple camera position
    eye = np.array([
        distance * np.cos(angle),
        height,
        distance * np.sin(angle)
    ])
    
    # Create view matrix
    view = np.eye(4, dtype=np.float32)
    view[:3, 3] = -eye  # Translation
    
    # Create projection matrix
    proj = np.eye(4, dtype=np.float32)
    proj[0, 0] = 1.0     # Aspect ratio
    proj[1, 1] = -1.0    # Flip Y for Vulkan
    proj[2, 2] = 0.5     # Depth range
    proj[2, 3] = 0.5
    proj[3, 2] = -1.0    # Perspective
    
    # Update camera
    print(f"  Updating camera (angle={{np.degrees(angle):.0f}}°, dist={{distance:.1f}})")
    if client.update_camera(view, proj):
        print("  ✅ Camera updated")
        
        # Try to get frame
        try:
            print("  ⏳ Waiting for frame...")
            frame = client.get_frame(timeout_ms=3000)
            
            if frame is not None:
                print(f"  ✅ Frame captured: {{frame.shape}} {{frame.dtype}}")
                
                # Check if it's on GPU
                if hasattr(frame, 'device'):
                    print(f"     Device: {{frame.device}}")
                
                # Save PNG
                filename = f"vk2torch_frame_{{i:02d}}.png"
                if client.save_frame_png(frame, filename):
                    print(f"  ✅ Saved {{filename}}")
                    success_count += 1
                else:
                    print(f"  ⚠️  Failed to save {{filename}}")
            else:
                print("  ⚠️  Frame is None (timeout)")
        except Exception as e:
            print(f"  ❌ Error: {{e}}")
    else:
        print("  ❌ Camera update failed")
    
    # Small delay between frames
    time.sleep(0.5)

# Disconnect
client.disconnect()
print(f"\\n✅ Disconnected")

# Report results
print("\\n" + "="*50)
print("📊 RESULTS")
print("="*50)
if success_count > 0:
    print(f"✅ Successfully captured {{success_count}}/5 frames")
    
    # List PNG files
    import os
    png_files = [f for f in os.listdir('.') if f.startswith('vk2torch_frame_') and f.endswith('.png')]
    if png_files:
        print(f"\\n📸 PNG files created:")
        for png in sorted(png_files):
            size = os.path.getsize(png)
            print(f"   ✅ {{png}} ({{size:,}} bytes)")
    
    sys.exit(0)
else:
    print("❌ No frames were captured successfully")
    sys.exit(1)
"""
    
    # Run Python test with conda environment
    conda_activate = "source /home/gongyuning/anaconda3/bin/activate vk2torch"
    python_cmd = f"cd {python_dir} && python -c '{test_script}'"
    full_cmd = f"{conda_activate} && {python_cmd}"
    
    result = subprocess.run(
        full_cmd,
        shell=True,
        executable='/bin/bash',
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
    
    success = result.returncode == 0
    
    # Step 3: Clean up
    print("\n📌 Step 3: Cleaning up...")
    
    # Terminate Vulkan
    print("Terminating Vulkan process...")
    vulkan_process.terminate()
    try:
        vulkan_process.wait(timeout=3)
        print("✅ Vulkan process terminated")
    except subprocess.TimeoutExpired:
        vulkan_process.kill()
        print("✅ Vulkan process killed")
    
    # Remove socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
        print("✅ Socket removed")
    
    return success

if __name__ == "__main__":
    print("VK2TORCH Complete Test")
    print("This will:")
    print("1. Start the Vulkan application")
    print("2. Connect with Python client")
    print("3. Capture 5 frames from different angles")
    print("4. Save them as PNG files")
    print("")
    
    success = run_complete_test()
    
    if success:
        print("\n" + "="*70)
        print("🎉 TEST COMPLETED SUCCESSFULLY!")
        print("Check the python/ directory for vk2torch_frame_*.png files")
        print("="*70)
    else:
        print("\n" + "="*70)
        print("❌ TEST FAILED")
        print("Check the output above for errors")
        print("="*70)
    
    sys.exit(0 if success else 1)