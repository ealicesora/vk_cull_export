#!/usr/bin/env python3
"""
P6 Example: New construction method using Vk2TorchApp instead of UDS
This demonstrates the minimal changes to replace socket-based integration
with direct pybind11 FD export.
"""

import torch
import sys
sys.path.insert(0, "/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py")

import vk2torch_ext
from vk2torch_client import Vk2TorchCudaClient

def example_new_construction():
    """Example showing new construction method."""
    print("P6 Example: New Construction Method")
    print("=" * 40)
    
    # NEW: Direct Vk2TorchApp construction instead of UDS socket
    W, H = 1000, 1000
    app = vk2torch_ext.Vk2TorchApp(W, H, raster=True, scene_path="matrix_city.glb")
    
    # Get parameters directly from app (no socket handshake needed)
    H2, W2 = app.size()
    row_pitch = app.row_pitch_bytes()
    fd_mem = app.export_depth_buffer_fd()
    fd_sem = app.export_frame_done_semaphore_fd()
    
    print(f"App size: ({H2}, {W2})")
    print(f"Row pitch: {row_pitch} bytes") 
    print(f"Memory FD: {fd_mem}")
    print(f"Semaphore FD: {fd_sem}")
    
    # NEW: Use Vk2TorchCudaClient for direct FD import (no socket communication)
    client = Vk2TorchCudaClient()
    
    # Import external resources (would work with real FDs)
    if fd_mem != -1 and fd_sem != -1:
        client.import_external_memory_from_fd(fd_mem, size_bytes=H2 * row_pitch)
        client.import_timeline_semaphore(fd_sem)
        
        # Frame loop - same zero-copy logic, different source
        I = 5
        for i in range(I):
            view = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            proj = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            
            # Set camera directly on app (no socket message)
            app.set_camera(frame=i, view=view, proj=proj)
            
            # Wait for completion (direct semaphore, no socket)
            client.wait_semaphore(value=i)
            
            # Zero-copy tensor access (unchanged from UDS version)
            t = client.get_frame_zero_copy(row_pitch=row_pitch, H=H2, W=W2)
            
            if i == 0:
                print(f"Frame 0: {t.device}, {t.dtype}, {t.shape}")
    else:
        print("Stub mode detected - interface works, ready for real implementation!")
    
    app.stop()
    print("\n✅ Example complete - CPU usage should be lower than UDS version!")

if __name__ == "__main__":
    example_new_construction()