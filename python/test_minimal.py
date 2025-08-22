#!/usr/bin/env python3
"""
Minimal test - just connect and wait for 2 frames
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

socket_path = "/tmp/vk2torch.sock"

print("MINIMAL TEST: Just wait for 2 frames")
print("=" * 50)

# Import and connect
import vk2torch_client
client = vk2torch_client.VK2TorchClient(socket_path)

if not client.connect():
    print("❌ Failed to connect")
    sys.exit(1)

print(f"✅ Connected: {client.width}x{client.height}")
print(f"   Frame counter starts at: {client.frame_number}")

# Vulkan will render frames 1 and 2 without waiting
# So we just wait for them
for i in [1, 2]:
    print(f"\n[Frame {i}]")
    print(f"  Python frame_number before wait: {client.frame_number}")
    
    # IMPORTANT: get_frame waits for self.frame_number
    client.frame_number = i  # Set to the frame we want to wait for
    
    try:
        frame = client.get_frame(timeout_ms=3000)
        if frame is not None:
            print(f"  ✅ Got frame {i}: {frame.shape}")
            filename = f"minimal_{i}.png"
            if client.save_frame_png(frame, filename):
                print(f"  ✅ Saved {filename}")
        else:
            print(f"  ❌ Frame {i} timeout")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    print(f"  Python frame_number after wait: {client.frame_number}")

print("\n✅ Disconnecting...")
client.disconnect()
print("Done")