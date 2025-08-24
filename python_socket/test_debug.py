#!/usr/bin/env python3
"""
Debug test for VK2Torch synchronization
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
    print("VK2TORCH DEBUG TEST")
    print("=" * 50)
    
    # Import client
    import vk2torch_client
    
    # Check socket
    if not os.path.exists(socket_path):
        print(f"❌ Socket {socket_path} does not exist!")
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
    print(f"   Initial frame number: {client.frame_number}")
    
    if not client.has_cuda_support:
        print("\n⚠️  No CUDA support - continuing anyway")
    
    # Wait for Vulkan to be ready
    print("\n⏳ Waiting 2 seconds for Vulkan render loop to start...")
    time.sleep(2)
    
    # Test frame synchronization
    print("\n📸 Testing frame synchronization...")
    print("-" * 50)
    
    # The first 2 frames are skipped by Vulkan, so we need to account for that
    # Vulkan starts at frame 1, skips waiting for frames 1 and 2
    
    # Frame 1 and 2: Vulkan skips waiting, so we shouldn't send signals for these
    print("\n[Frame 1-2] Vulkan will skip waiting for these frames")
    
    # Start from frame 3 where Vulkan starts waiting
    for frame_num in range(3, 8):  # Test frames 3-7
        print(f"\n[Frame {frame_num}]")
        
        # Create camera matrices
        angle = (frame_num - 3) * (np.pi / 3)  # Different angle for each frame
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
        
        print(f"  Setting frame number to {frame_num} before update")
        client.frame_number = frame_num
        
        print(f"  Sending camera update for frame {frame_num}...")
        try:
            if client.update_camera(view, proj):
                print(f"  ✅ Camera updated (signaled frame {client.frame_number - 1})")
            else:
                print(f"  ❌ Camera update failed")
                continue
        except Exception as e:
            print(f"  ❌ Camera update exception: {e}")
            continue
        
        print(f"  Waiting for frame {frame_num} to complete...")
        try:
            # Wait for frame with matching number
            frame = client.get_frame(timeout_ms=2000)
            
            if frame is not None:
                print(f"  ✅ Frame received: {frame.shape}")
                
                # Save PNG
                filename = f"frame_{frame_num:03d}.png"
                if client.save_frame_png(frame, filename):
                    if Path(filename).exists():
                        size = Path(filename).stat().st_size
                        print(f"  ✅ Saved {filename} ({size:,} bytes)")
                    else:
                        print(f"  ⚠️  File not found after save")
                else:
                    print(f"  ❌ Failed to save PNG")
            else:
                print(f"  ❌ Frame timeout")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        # Small delay between frames
        time.sleep(0.1)
    
    # Disconnect
    print("\n📌 Disconnecting...")
    client.disconnect()
    print("✅ Done")
    
    # Check results
    png_files = list(Path(".").glob("frame_*.png"))
    if png_files:
        print(f"\n🎉 SUCCESS! Created {len(png_files)} PNG files:")
        for png in sorted(png_files):
            print(f"   {png.name}")
    else:
        print("\n❌ No PNG files created")
    
    return 0 if png_files else 1

if __name__ == "__main__":
    sys.exit(main())