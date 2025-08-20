#!/usr/bin/env python3
"""
Simple test to capture just one frame
"""

import os
import sys
import time
import numpy as np
from pathlib import Path

# Add Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_simple():
    socket_path = "/tmp/simple_test.sock"
    
    print("Simple Frame Capture Test")
    print("=" * 50)
    
    # Import client
    import vk2torch_client
    
    # Create client
    print("Creating client...")
    client = vk2torch_client.VK2TorchClient(socket_path)
    
    # Connect
    print("Connecting...")
    if not client.connect():
        print("❌ Failed to connect")
        print("Make sure Vulkan app is running with:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --renderer 0 --validation 0 --gridcopies 1")
        return False
    
    print(f"✅ Connected: {client.width}x{client.height}")
    print(f"   CUDA: {client.has_cuda_support}")
    
    if not client.has_cuda_support:
        print("⚠️  No CUDA support")
        client.disconnect()
        return False
    
    # Wait a bit for Vulkan to be ready
    print("\nWaiting for Vulkan to be ready...")
    time.sleep(1)
    
    # Send camera update
    print("\nSending camera update...")
    view = np.eye(4, dtype=np.float32)
    proj = np.eye(4, dtype=np.float32)
    
    if client.update_camera(view, proj):
        print("✅ Camera updated (frame 1 signaled)")
    else:
        print("❌ Camera update failed")
        client.disconnect()
        return False
    
    # Wait for frame
    print("\nWaiting for frame...")
    try:
        frame = client.get_frame(timeout_ms=5000)
        if frame is not None:
            print(f"✅ Frame received: {frame.shape} on {frame.device}")
            
            # Save PNG
            filename = "simple_test.png"
            if client.save_frame_png(frame, filename):
                size = Path(filename).stat().st_size
                print(f"✅ Saved {filename} ({size:,} bytes)")
                print("\n🎉 SUCCESS!")
                success = True
            else:
                print(f"❌ Failed to save {filename}")
                success = False
        else:
            print("❌ Frame is None (timeout)")
            success = False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    # Disconnect
    client.disconnect()
    print("\n✅ Disconnected")
    
    return success

if __name__ == "__main__":
    # First, check if Vulkan is running
    socket_path = "/tmp/simple_test.sock"
    
    if not os.path.exists(socket_path):
        print("⚠️  Socket doesn't exist. Start Vulkan first:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --renderer 0 --validation 0 --gridcopies 1")
        print("\nThen run this test again.")
        sys.exit(1)
    
    # Run test
    success = test_simple()
    sys.exit(0 if success else 1)