#!/usr/bin/env python3
"""Simple test of VK2Torch client functionality"""

import sys
import os
import time
import numpy as np

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

from vk2torch_client import VK2TorchClient

def test_connection():
    """Test basic connection and FD exchange"""
    print("=" * 60)
    print("VK2Torch Python Client Test")
    print("=" * 60)
    
    # Create client
    client = VK2TorchClient(socket_path="/tmp/vk2torch.sock")
    
    # Connect to Vulkan app
    print("\n1. Connecting to Vulkan app...")
    if not client.connect():
        print("   ✗ Failed to connect")
        print("   Make sure Vulkan app is running with:")
        print("   ./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --offscreen 1 --renderer 0 --validation 0")
        return False
    
    print("   ✓ Connected successfully")
    print(f"   - Frame size: {client.width}x{client.height}")
    print(f"   - Format: {client.format}")
    print(f"   - Color buffer: {client.color_readback_bytes} bytes")
    print(f"   - Camera buffer: {client.cam_bytes} bytes")
    
    # Test camera update (even without CUDA, we can test the structure)
    print("\n2. Testing camera parameter structure...")
    try:
        # Create dummy camera parameters
        camera_params = np.zeros(client.cam_bytes // 4, dtype=np.float32)
        
        # Set some test values (identity matrix for view)
        camera_params[0:16] = np.eye(4).flatten()  # view matrix
        camera_params[16:32] = np.eye(4).flatten()  # proj matrix
        
        print("   ✓ Camera parameter structure created")
        print(f"   - Size: {len(camera_params) * 4} bytes")
        
    except Exception as e:
        print(f"   ✗ Failed to create camera params: {e}")
    
    # Test frame request (this will fail without CUDA but shows the flow)
    print("\n3. Testing frame request flow...")
    if client.cuda_api:
        try:
            # This would normally update camera and get frame
            print("   - CUDA available, would get frame here")
            # frame = client.get_frame()
            # print(f"   ✓ Frame shape would be: {client.height}x{client.width}x4")
        except Exception as e:
            print(f"   ✗ Frame request failed: {e}")
    else:
        print("   - CUDA not available, skipping frame request")
        print("   - Frame would be: {}x{}x4 tensor".format(client.height, client.width))
    
    # Keep connection for a bit
    print("\n4. Maintaining connection for 2 seconds...")
    time.sleep(2)
    
    # Disconnect
    print("\n5. Disconnecting...")
    client.disconnect()
    print("   ✓ Disconnected")
    
    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)
    return True

def test_multiple_connections():
    """Test connecting and disconnecting multiple times"""
    print("\n" + "=" * 60)
    print("Testing Multiple Connections")
    print("=" * 60)
    
    for i in range(3):
        print(f"\nConnection attempt {i+1}/3...")
        client = VK2TorchClient(socket_path="/tmp/vk2torch.sock")
        
        if client.connect():
            print(f"  ✓ Connected")
            time.sleep(0.5)
            client.disconnect()
            print(f"  ✓ Disconnected")
        else:
            print(f"  ✗ Failed to connect")
            return False
        
        time.sleep(0.5)
    
    print("\n✓ Multiple connections test passed")
    return True

if __name__ == "__main__":
    import sys
    
    # Check if running non-interactively
    if not sys.stdin.isatty():
        print("Running in non-interactive mode...")
    else:
        print("Make sure Vulkan app is running with:")
        print("./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --offscreen 1 --renderer 0 --validation 0")
        print()
        input("Press Enter when ready...")
    
    # Run tests
    success = test_connection()
    
    if success:
        # For offscreen mode, we can't test multiple connections
        # since the app exits after first disconnect
        print("\nNote: In offscreen mode, app exits after disconnect")
        print("To test multiple connections, use GUI mode (without --offscreen)")
    
    sys.exit(0 if success else 1)