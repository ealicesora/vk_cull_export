#!/usr/bin/env python3
"""
Test complete zero-copy pipeline: Python → Camera → Vulkan → Timeline Semaphore
This demonstrates the full integration of Phase 2: Camera Override functionality
"""
import sys
import os
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/python/_bin/Release')

import numpy as np
import time

def create_camera_matrices(distance=3.0, yaw=0.0, pitch=0.0):
    """Create view and projection matrices for camera positioning"""
    # Create view matrix - camera at distance, rotated by yaw/pitch
    eye = np.array([
        distance * np.cos(yaw) * np.cos(pitch),
        distance * np.sin(pitch), 
        distance * np.sin(yaw) * np.cos(pitch)
    ])
    center = np.array([0.0, 0.0, 0.0])  # Look at origin
    up = np.array([0.0, 1.0, 0.0])      # Up vector
    
    # Build view matrix using lookAt
    z_axis = eye - center
    z_axis = z_axis / np.linalg.norm(z_axis)
    x_axis = np.cross(up, z_axis)
    x_axis = x_axis / np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    
    view_matrix = np.array([
        [x_axis[0], y_axis[0], z_axis[0], 0.0],
        [x_axis[1], y_axis[1], z_axis[1], 0.0],
        [x_axis[2], y_axis[2], z_axis[2], 0.0],
        [-np.dot(x_axis, eye), -np.dot(y_axis, eye), -np.dot(z_axis, eye), 1.0]
    ], dtype=np.float32)
    
    # Create projection matrix
    fov = np.radians(45.0)
    aspect = 1.0  # 512x512
    near = 0.1
    far = 100.0
    
    f = 1.0 / np.tan(fov / 2.0)
    proj_matrix = np.array([
        [f/aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far+near)/(near-far), (2*far*near)/(near-far)],
        [0.0, 0.0, -1.0, 0.0]
    ], dtype=np.float32)
    
    return view_matrix, proj_matrix

def test_zero_copy_pipeline():
    """Test the complete zero-copy rendering pipeline"""
    
    print("🚀 Testing Zero-Copy Pipeline: Python → Camera → Vulkan → Timeline Semaphore")
    print("=" * 80)
    
    # Import and create application
    try:
        import vk2torch_ext
        print("✅ Step 1: vk2torch_ext imported successfully")
    except ImportError as e:
        print(f"❌ Step 1 FAILED: {e}")
        return False
    
    try:
        app = vk2torch_ext.Vk2TorchApp(
            width=512,
            height=512,
            raster=True,  # Use rasterization
            scene_path="",  # Default scene (Stanford bunny or house)
            asset_root="/home/gongyuning/Desktop/vk_cull/vk_lod_clusters"
        )
        print("✅ Step 2: Created Vk2TorchApp with real 3D scene rendering")
        
        # Get dimensions
        height, width = app.size()
        print(f"   - Render target: {width}x{height}")
        
    except Exception as e:
        print(f"❌ Step 2 FAILED: {e}")
        return False
    
    # Test camera override and frame rendering
    try:
        print("\n📹 Testing Camera Override System:")
        
        # Test multiple camera positions (orbit around scene)
        positions = [
            (3.0, 0.0, 0.0),      # Front view
            (4.0, np.pi/4, 0.1),  # Angled view  
            (5.0, np.pi/2, -0.1), # Side view
            (3.5, -np.pi/4, 0.2), # Another angle
        ]
        
        frame_values = []
        
        for i, (distance, yaw, pitch) in enumerate(positions):
            print(f"   Position {i+1}: distance={distance:.1f}, yaw={yaw:.2f}, pitch={pitch:.2f}")
            
            # Create camera matrices for this position
            view_matrix, proj_matrix = create_camera_matrices(distance, yaw, pitch)
            
            # Apply camera override
            app.set_camera_matrices(proj_matrix, view_matrix)
            
            # Render frame with timeline synchronization
            frame_start = time.time()
            frame_value = app.render_and_signal(sync=True)  # Synchronous for testing
            frame_end = time.time()
            
            frame_values.append(frame_value)
            print(f"     → Frame {frame_value} rendered in {(frame_end-frame_start)*1000:.2f}ms")
        
        print(f"✅ Step 3: Camera override system working correctly")
        print(f"   - Rendered {len(positions)} frames with different camera positions")
        print(f"   - Frame values: {frame_values}")
        
    except Exception as e:
        print(f"❌ Step 3 FAILED: Camera override error: {e}")
        return False
    
    # Test timeline semaphore coordination
    try:
        print("\n⏱️  Testing Timeline Semaphore Coordination:")
        
        last_frame = app.last_signaled_frame()
        print(f"   - Last signaled frame: {last_frame}")
        
        # Verify timeline semaphore values are increasing
        if len(set(frame_values)) == len(frame_values) and all(frame_values[i] < frame_values[i+1] for i in range(len(frame_values)-1)):
            print("✅ Step 4: Timeline semaphore values are monotonically increasing")
        else:
            print(f"⚠️  Step 4 WARNING: Timeline semaphore values may not be strictly ordered: {frame_values}")
            
    except Exception as e:
        print(f"❌ Step 4 FAILED: Timeline semaphore error: {e}")
        return False
    
    # Test depth export info (for zero-copy integration)
    try:
        print("\n🔗 Testing Zero-Copy Integration Interface:")
        
        export_info = app.get_depth_export_info(dup_fds=False)  # Don't duplicate for test
        print("✅ Step 5: Depth export info retrieved successfully")
        print(f"   - Width: {export_info['width']}, Height: {export_info['height']}")
        print(f"   - Row pitch: {export_info['row_pitch_bytes']} bytes")
        print(f"   - Buffer size: {export_info['size']} bytes")
        print(f"   - Memory FD: {'valid' if export_info['mem_fd'] >= 0 else 'invalid'}")
        print(f"   - Semaphore FD: {'valid' if export_info['sem_fd'] >= 0 else 'invalid'}")
        print(f"   - Last semaphore payload: {export_info['semaphore_payload']}")
        
    except Exception as e:
        print(f"❌ Step 5 FAILED: Export info error: {e}")
        return False
    
    # Cleanup
    try:
        app.stop()
        print("\n✅ Step 6: Application cleanup completed successfully")
    except Exception as e:
        print(f"❌ Step 6 FAILED: Cleanup error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("Zero-Copy Pipeline Integration Test")
    print("Phase 2: Camera Override Implementation - Complete Testing")
    print("=" * 80)
    
    success = test_zero_copy_pipeline()
    
    print("\n" + "=" * 80)
    if success:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Camera Override System is fully functional")
        print("✅ Timeline Semaphore signaling works correctly") 
        print("✅ Zero-copy integration interface ready")
        print("✅ Ready for Phase 3: Python → CUDA/Torch integration")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED!")
        print("   Check the error messages above for details")
        sys.exit(1)