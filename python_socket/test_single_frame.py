#!/usr/bin/env python3
"""
Simple single frame test for VK2Torch
"""

import os
import sys
import time
import numpy as np
from pathlib import Path

# Add Python path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    socket_path = "/tmp/vk2torch.sock"
    
    print("=" * 50)
    print("VK2TORCH SINGLE FRAME TEST")
    print("=" * 50)
    
    # Import client
    import vk2torch_client
    
    # Check socket
    if not os.path.exists(socket_path):
        print(f"❌ Socket {socket_path} does not exist!")
        print("Start Vulkan first with:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --renderer 0 --validation 0 --gridcopies 1")
        return 1
    
    print(f"✅ Socket exists: {socket_path}")
    
    # Create and connect client
    print("\nConnecting...")
    client = vk2torch_client.VK2TorchClient(socket_path)
    
    if not client.connect():
        print("❌ Failed to connect")
        return 1
    
    print(f"✅ Connected: {client.width}x{client.height}")
    print(f"   CUDA: {client.has_cuda_support}")
    
    # Wait for stabilization
    print("\nWaiting 3 seconds for render loop...")
    time.sleep(3)
    
    # Send camera update
    print("\n📸 Capturing single frame...")
    view = np.eye(4, dtype=np.float32)
    proj = np.eye(4, dtype=np.float32)
    
    print("  Sending camera update...")
    if not client.update_camera(view, proj):
        print("  ❌ Camera update failed")
        client.disconnect()
        return 1
    
    print(f"  ✅ Camera updated (frame {client.frame_number})")
    
    # Get frame
    print("  Waiting for frame...")
    try:
        frame = client.get_frame(timeout_ms=5000)
        if frame is not None:
            print(f"  ✅ Frame received: {frame.shape} on {frame.device if hasattr(frame, 'device') else 'CPU'}")
            
            # Save PNG
            filename = "test_single.png"
            if client.save_frame_png(frame, filename):
                if Path(filename).exists():
                    size = Path(filename).stat().st_size
                    print(f"  ✅ Saved {filename} ({size:,} bytes)")
                    print("\n🎉 SUCCESS!")
                else:
                    print(f"  ❌ File {filename} not found after save")
            else:
                print(f"  ❌ Failed to save {filename}")
        else:
            print("  ❌ Frame is None (timeout)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Disconnect
    print("\nDisconnecting...")
    client.disconnect()
    print("✅ Done")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())