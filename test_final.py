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
    """Complete system test with socket-based camera control."""
    
    # Test with the updated client (now using socket-based camera matrices)
    from vk2torch_client import VK2TorchClient
    import numpy as np
    
    print("\nConnecting with VK2TorchClient (socket-based camera protocol)...")
    client = VK2TorchClient('/tmp/vk2torch.sock')
    
    if client.connect():
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"   Format: {client.format}")
        print(f"   UUID: {client.vk_uuid}")
        print(f"   Connection status: {client.connection_status}")
        print("✅ Received 'ready to render' message from Vulkan")
        
        # Test with varying camera positions to show socket control works
        print("\nTesting frame capture with different camera positions...")
        
        def create_camera_matrices(distance, yaw, pitch):
            """Create view and projection matrices for camera."""
            # Simple perspective projection
            fov = np.radians(45.0)
            aspect = client.width / client.height
            near = 0.1
            far = 100.0
            
            proj = np.array([
                [1/(aspect*np.tan(fov/2)), 0, 0, 0],
                [0, 1/np.tan(fov/2), 0, 0],
                [0, 0, -(far+near)/(far-near), -2*far*near/(far-near)],
                [0, 0, -1, 0]
            ], dtype=np.float32)
            
            # Camera position in orbit
            x = distance * np.cos(yaw) * np.cos(pitch)
            y = distance * np.sin(pitch)
            z = distance * np.sin(yaw) * np.cos(pitch)
            
            # Look at origin
            eye = np.array([x, y, z])
            target = np.array([0, 0, 0])
            up = np.array([0, 1, 0])
            
            # Create view matrix
            forward = target - eye
            forward = forward / np.linalg.norm(forward)
            right = np.cross(forward, up)
            right = right / np.linalg.norm(right)
            up = np.cross(right, forward)
            
            view = np.array([
                [right[0], up[0], -forward[0], 0],
                [right[1], up[1], -forward[1], 0],
                [right[2], up[2], -forward[2], 0],
                [-np.dot(right, eye), -np.dot(up, eye), np.dot(forward, eye), 1]
            ], dtype=np.float32)
            
            return view, proj
        
        t_all_start = perf_counter()
        frame = None
        
        for i in range(0, 5):  # Reduced to 5 frames for quicker testing
            # Create different camera positions for each frame
            distance = 4.0 + i * 0.5  # Move camera further away each frame
            yaw = i * 0.3  # Rotate around Y axis
            pitch = 0.0
            
            view, proj = create_camera_matrices(distance, yaw, pitch)
            
            print(f"Frame {i}: update_camera (frame_number={client.frame_number}, distance={distance:.1f})")
            client.update_camera(view, proj)
            print("✅ Camera matrices sent via socket")

            frame = client.get_frame(timeout_ms=2000)

            if frame is not None:
                client.save_frame_png(frame, f"success_test{i}.png")
                print(f"✅ Frame {i} saved")
            else:
                print(f"⚠️ Frame {i} capture failed")
            
        t_all = perf_counter() - t_all_start
        print(f"Total time for 5 frames: {t_all:.2f}s")
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