#!/usr/bin/env python3
"""
Passive test - just wait for frames without sending camera updates
This tests if the frame done semaphores work
"""

import os
import sys
import time
from pathlib import Path

# Add Python path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    socket_path = "/tmp/vk2torch.sock"
    
    print("=" * 50)
    print("VK2TORCH PASSIVE TEST")
    print("Just waiting for frames without sending camera updates")
    print("=" * 50)
    
    # Import client
    import vk2torch_client
    
    # Check socket
    if not os.path.exists(socket_path):
        print(f"❌ Socket {socket_path} does not exist!")
        return 1
    
    # Create and connect client
    print("\nConnecting...")
    client = vk2torch_client.VK2TorchClient(socket_path)
    
    if not client.connect():
        print("❌ Failed to connect")
        return 1
    
    print(f"✅ Connected: {client.width}x{client.height}")
    print(f"   CUDA: {client.has_cuda_support}")
    
    print("\n📸 Passively waiting for frames...")
    print("-" * 50)
    
    captured_frames = []
    
    # Just try to get frames 1 and 2 which Vulkan should render without waiting
    for frame_num in [1, 2]:
        print(f"\n[Frame {frame_num}] Trying to capture...")
        
        # Set frame number for get_frame to wait for
        client.frame_number = frame_num + 1  # get_frame decrements
        
        try:
            # Just wait for the frame
            frame = client.get_frame(timeout_ms=3000)
            if frame is not None:
                print(f"  ✅ Frame {frame_num} received: {frame.shape}")
                filename = f"passive_frame_{frame_num:03d}.png"
                if client.save_frame_png(frame, filename):
                    captured_frames.append(filename)
                    print(f"  ✅ Saved {filename}")
            else:
                print(f"  ❌ Frame {frame_num} timeout")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Disconnect
    print("\n📌 Disconnecting...")
    client.disconnect()
    print("✅ Done")
    
    # Check results
    if captured_frames:
        print(f"\n🎉 SUCCESS! Captured {len(captured_frames)} frames:")
        for filename in captured_frames:
            if Path(filename).exists():
                size = Path(filename).stat().st_size
                print(f"   {filename} ({size:,} bytes)")
    else:
        print("\n❌ No frames captured")
    
    return 0 if captured_frames else 1

if __name__ == "__main__":
    sys.exit(main())