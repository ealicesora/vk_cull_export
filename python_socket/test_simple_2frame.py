#!/usr/bin/env python3
"""Simple 2-frame test that avoids synchronization issues."""

import sys
import time
import numpy as np
sys.path.insert(0, 'python')

def test_simple_2frame():
    """Test capturing exactly 2 frames without complex synchronization."""
    from vk2torch_client import VK2TorchClient
    
    print("Starting simple 2-frame test...")
    client = VK2TorchClient('/tmp/vk2torch.sock')
    
    if not client.connect():
        print("Failed to connect!")
        return False
    
    print(f"Connected: {client.width}x{client.height}")
    
    # Give the system time to stabilize after connection
    time.sleep(0.5)
    
    # Capture 2 frames
    for i in range(2):
        print(f"\n=== Frame {i+1} ===")
        
        # Update camera
        view = np.eye(4, dtype=np.float32)
        proj = np.eye(4, dtype=np.float32)
        
        print(f"Updating camera for frame {i+1}...")
        client.update_camera(view, proj)
        
        # Get frame with a reasonable timeout
        print(f"Waiting for frame {i+1}...")
        frame = client.get_frame(timeout_ms=5000)
        
        if frame is not None:
            # Save the frame
            filename = f'frame_{i+1:03d}.png'
            client.save_frame_png(frame, filename)
            print(f"✅ Frame {i+1} saved to {filename}")
        else:
            print(f"❌ Frame {i+1} timed out or failed")
            return False
        
        # Small delay between frames
        time.sleep(0.2)
    
    print("\n✅ Successfully captured 2 frames!")
    
    # Clean disconnect
    if hasattr(client, 'close'):
        client.close()
    
    return True

if __name__ == "__main__":
    success = test_simple_2frame()
    sys.exit(0 if success else 1)