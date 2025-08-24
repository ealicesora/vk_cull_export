#!/usr/bin/env python3
"""
Fixed synchronization test for VK2Torch
Handles the frame number mismatch correctly
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
    print("VK2TORCH SYNC FIX TEST")
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
    
    # IMPORTANT: Vulkan skips waiting for frames 1 and 2
    # So we shouldn't signal camera ready for those frames
    # We should just wait for frame done 1 and 2
    
    print("\n📸 Testing with correct synchronization...")
    print("-" * 50)
    
    captured_frames = []
    
    # Handle frames 1 and 2 (Vulkan skips waiting for these)
    for frame_num in [1, 2]:
        print(f"\n[Frame {frame_num}] Vulkan will skip waiting")
        # Don't signal camera ready - Vulkan won't wait for it
        # Just wait for frame done
        print(f"  Waiting for frame done {frame_num}...")
        
        # Set frame number for get_frame to wait for
        client.frame_number = frame_num + 1  # get_frame will wait for frame_num
        
        try:
            # get_frame decrements frame_number and waits for that
            frame = client.get_frame(timeout_ms=2000)
            if frame is not None:
                print(f"  ✅ Frame {frame_num} received: {frame.shape}")
                filename = f"frame_{frame_num:03d}.png"
                if client.save_frame_png(frame, filename):
                    captured_frames.append(filename)
                    print(f"  ✅ Saved {filename}")
            else:
                print(f"  ❌ Frame {frame_num} timeout")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # Now handle frames 3+ where Vulkan waits for camera ready
    for frame_num in range(3, 6):
        print(f"\n[Frame {frame_num}] Normal synchronization")
        
        # Create camera matrices
        angle = (frame_num - 3) * (np.pi / 2)
        distance = 5.0 + (frame_num - 3) * 0.5
        
        eye = np.array([
            distance * np.cos(angle),
            2.0,
            distance * np.sin(angle)
        ])
        
        view = np.eye(4, dtype=np.float32)
        view[:3, 3] = -eye
        
        proj = np.eye(4, dtype=np.float32)
        proj[1, 1] = -1.0  # Flip Y for Vulkan
        
        # Set frame number and update camera
        client.frame_number = frame_num
        
        print(f"  Signaling camera ready {frame_num}...")
        if client.update_camera(view, proj):
            print(f"  ✅ Camera ready {frame_num} signaled")
            
            # Wait for frame done
            print(f"  Waiting for frame done {frame_num}...")
            try:
                frame = client.get_frame(timeout_ms=2000)
                if frame is not None:
                    print(f"  ✅ Frame {frame_num} received: {frame.shape}")
                    filename = f"frame_{frame_num:03d}.png"
                    if client.save_frame_png(frame, filename):
                        captured_frames.append(filename)
                        print(f"  ✅ Saved {filename}")
                else:
                    print(f"  ❌ Frame {frame_num} timeout")
            except Exception as e:
                print(f"  ❌ Error: {e}")
        else:
            print(f"  ❌ Failed to signal camera ready {frame_num}")
    
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