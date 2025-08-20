#!/usr/bin/env python3
"""Interactive test for VK2Torch - can be run in IPython/Jupyter"""

from vk2torch_client import VK2TorchClient
import numpy as np
import time

# Start Vulkan app first:
# ./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0

# Create client
client = VK2TorchClient(socket_path="/tmp/test.sock")

# Connect
if client.connect():
    print(f"✓ Connected! Status: {client.connection_status}")
    print(f"  Frame size: {client.width}x{client.height}")
    print(f"  Format: {client.format}")
    print(f"  Color buffer: {client.color_readback_bytes} bytes")
    print(f"  Camera buffer: {client.cam_bytes} bytes")
    
    # Check CUDA support
    if client.has_cuda_support:
        print("\n✓ CUDA support available - full functionality enabled")
        print("  You can call:")
        print("  - client.get_frame() to capture frames")
        print("  - client.update_camera() to change camera")
    else:
        print("\n⚠ CUDA support not available - running in test mode")
        print("  Connection is active but frame capture is disabled")
        print("  This is likely due to CUDA external memory import issues")
        print("  You can still test connection and metadata access")
    
    # Keep connection open for interactive use
    print("\n📌 Connection open. Use client.disconnect() when done")
    print("  - GUI mode: app keeps running after disconnect")
    print("  - Offscreen mode: app exits after disconnect")
else:
    print("✗ Failed to connect. Is Vulkan app running with --uds?")

# Example camera update (if CUDA available)
def update_camera(client, angle=0.0):
    """Example of updating camera parameters"""
    if not client.cuda_api:
        print("CUDA not available")
        return
    
    # Create camera matrix with rotation
    cam_data = np.zeros(client.cam_bytes // 4, dtype=np.float32)
    
    # Simple rotation matrix
    c, s = np.cos(angle), np.sin(angle)
    view = np.array([
        [c, 0, s, 0],
        [0, 1, 0, 0],
        [-s, 0, c, 5],  # 5 units back
        [0, 0, 0, 1]
    ])
    
    # Perspective projection
    proj = np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, -1.1, -2],
        [0, 0, -1, 0]
    ])
    
    cam_data[0:16] = view.flatten()
    cam_data[16:32] = proj.flatten()
    
    # Update and get frame
    # client.update_camera_params(cam_data)
    # frame = client.get_frame()
    # return frame
    
print("\nExample function available: update_camera(client, angle)")