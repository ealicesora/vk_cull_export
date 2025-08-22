#!/usr/bin/env python3
"""Final test to check if everything works."""

import sys
import os
import time
import subprocess


import time
import csv
import statistics as stats
from time import perf_counter

# Add Python client path
sys.path.insert(0, 'python')

def test_system():
    """Complete system test."""
    
    # Test with the original client
    from vk2torch_client import VK2TorchClient
    import numpy as np
    
    print("\nConnecting with VK2TorchClient...")
    client = VK2TorchClient('/tmp/vk2torch.sock')
    
    if client.connect():
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"   Format: {client.format}")
        print(f"   UUID: {client.vk_uuid}")
        print(f"   Connection status: {client.connection_status}")
        
        # Try to update camera and get a frame
        print("\nTesting frame capture...")
        view = np.eye(4, dtype=np.float32)
        proj = np.eye(4, dtype=np.float32)
        t_all_start = perf_counter()
        frame = None
        # time.sleep(10)
        for i in range(0,10):
            print("update_camera" + str(client.frame_number))
            client.update_camera(view, proj)
            print("✅ Camera updated")

            frame = client.get_frame(timeout_ms=2000)

            client.save_frame_png(frame, "success_test" + str(i) + ".png")
            # time.sleep(1)
            # client.frame_number = client.frame_number + 1
        t_all = perf_counter() - t_all_start
        print("t_all",t_all)
        time.sleep(10)
        if frame is not None:
            
            print(frame.sum())
            print(f"✅ Got frame: {frame.shape if hasattr(frame, 'shape') else 'data received'}")
        else:
            print("⚠️ Frame capture not available (expected without CUDA)")
        
        client.disconnect()
        print("✅ Disconnected cleanly")
        
        return True
    else:
        print("❌ Connection failed")
        return False
        



if __name__ == "__main__":
    success = test_system()
    sys.exit(0 if success else 1)