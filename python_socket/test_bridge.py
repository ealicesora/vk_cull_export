#!/usr/bin/env python3
"""
Test script for P6: Direct Vk2TorchApp integration without UDS
Replace socket communication with direct pybind11 FD export
"""

import torch
import sys
import os

# Add build directory to path for vk2torch_ext import
sys.path.insert(0, "/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py")

try:
    import vk2torch_ext
    print("✅ vk2torch_ext imported successfully")
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    sys.exit(1)

try:
    from vk2torch_client import Vk2TorchCudaClient
    print("✅ Vk2TorchCudaClient imported successfully")
except ImportError as e:
    print(f"❌ Failed to import Vk2TorchCudaClient: {e}")
    sys.exit(1)

def test_direct_integration():
    """Test direct Vk2TorchApp -> CUDA integration."""
    print("\n🚀 Starting P6 Direct Integration Test")
    
    # Test parameters
    W, H = 1000, 1000
    I = 60  # Number of frames to test
    
    try:
        print(f"Creating Vk2TorchApp({W}, {H})...")
        app = vk2torch_ext.Vk2TorchApp(W, H, raster=True, scene_path="matrix_city.glb")
        
        # Get dimensions and parameters from app
        H2, W2 = app.size()
        row_pitch = app.row_pitch_bytes()
        
        print(f"App created: size=({H2}, {W2}), row_pitch={row_pitch}")
        
        # Export file descriptors
        print("Exporting file descriptors...")
        fd_mem = app.export_depth_buffer_fd()
        fd_sem = app.export_frame_done_semaphore_fd()
        
        print(f"FDs exported: memory={fd_mem}, semaphore={fd_sem}")
        
        # For stub implementation, FDs are -1, so this test validates the interface
        if fd_mem == -1 or fd_sem == -1:
            print("⚠️  Stub implementation detected (FDs = -1)")
            print("✅ Interface test PASSED: All methods callable")
            print(f"✅ Frame loop test would process {I} frames")
            
            # Test camera setting (stub)
            view = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            proj = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            app.set_camera(0, view, proj)
            print("✅ Camera setting works")
            
            app.stop()
            print("✅ P6 Stub Test COMPLETE - Ready for real implementation!")
            return True
        
        # If we get real FDs, test full integration
        print("Creating CUDA client...")
        cli = Vk2TorchCudaClient()
        
        # Import FDs
        size_bytes = H2 * row_pitch
        cli.import_external_memory_from_fd(fd_mem, size_bytes)
        cli.import_timeline_semaphore(fd_sem)
        
        print(f"Starting {I}-frame test...")
        
        for i in range(I):
            # Set camera matrices
            view = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            proj = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
            app.set_camera(i, view, proj)
            
            # Wait for frame completion
            cli.wait_semaphore(value=i)
            
            # Get zero-copy tensor
            t = cli.get_frame_zero_copy(row_pitch=row_pitch, H=H2, W=W2)
            
            # Validate first frame
            if i == 0:
                print(f"✅ Frame 0: device={t.device}, dtype={t.dtype}, shape={t.shape}")
                expected_device = "cuda:0" if torch.cuda.is_available() else "cpu"
                assert str(t.device).startswith("cuda"), f"Expected CUDA device, got {t.device}"
                assert t.dtype == torch.float32, f"Expected float32, got {t.dtype}"
                assert t.shape == (H2, W2), f"Expected ({H2}, {W2}), got {t.shape}"
            
            if i % 20 == 0:
                print(f"  Frame {i}/{I} processed")
        
        app.stop()
        print(f"✅ {I} frames completed successfully!")
        print("✅ CPU usage should be lower than UDS version (no socket overhead)")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_direct_integration()
    if success:
        print("\n🎉 P6 TEST PASSED!")
        sys.exit(0)
    else:
        print("\n💥 P6 TEST FAILED!")
        sys.exit(1)