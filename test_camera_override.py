#!/usr/bin/env python3
"""
Test camera override functionality in vk2torch_ext
"""
import sys
import os
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/python/_bin/Release')

import numpy as np

# Test basic import
try:
    import vk2torch_ext
    print("✅ vk2torch_ext imported successfully")
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    sys.exit(1)

# Create application instance
try:
    app = vk2torch_ext.Vk2TorchApp(
        width=512,
        height=512,
        raster=True,  # Use rasterization for compatibility
        scene_path="",  # Default scene
        asset_root="/home/gongyuning/Desktop/vk_cull/vk_lod_clusters"
    )
    print("✅ Vk2TorchApp created successfully")
except Exception as e:
    print(f"❌ Failed to create Vk2TorchApp: {e}")
    sys.exit(1)

# Test camera matrix setting
try:
    # Create simple camera matrices
    # View matrix: camera looking at origin from (0, 0, 3)
    view_matrix = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, -3.0],
        [0.0, 0.0, 0.0, 1.0]
    ], dtype=np.float32)
    
    # Projection matrix: simple perspective
    fov = np.radians(45.0)
    aspect = 512.0 / 512.0
    near = 0.1
    far = 100.0
    
    f = 1.0 / np.tan(fov / 2.0)
    proj_matrix = np.array([
        [f/aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far+near)/(near-far), (2*far*near)/(near-far)],
        [0.0, 0.0, -1.0, 0.0]
    ], dtype=np.float32)
    
    app.set_camera_matrices(proj_matrix, view_matrix)
    print("✅ Camera matrices set successfully")
    
except Exception as e:
    print(f"❌ Failed to set camera matrices: {e}")
    sys.exit(1)

# Test frame rendering with camera override
try:
    frame_value = app.render_and_signal(sync=True)
    print(f"✅ Frame rendered successfully with value: {frame_value}")
    
    last_frame = app.last_signaled_frame()
    print(f"✅ Last signaled frame: {last_frame}")
    
except Exception as e:
    print(f"❌ Failed to render frame: {e}")
    sys.exit(1)

# Test multiple frames with different camera positions
try:
    for i in range(3):
        # Move camera around
        z_pos = 3.0 + i * 0.5
        view_matrix[2, 3] = -z_pos
        
        app.set_camera_matrices(proj_matrix, view_matrix)
        frame_value = app.render_and_signal(sync=True)
        print(f"✅ Frame {i+1} rendered at z={z_pos}, frame_value={frame_value}")
        
except Exception as e:
    print(f"❌ Failed to render multiple frames: {e}")
    sys.exit(1)

# Test cleanup
try:
    app.stop()
    print("✅ Application stopped successfully")
except Exception as e:
    print(f"❌ Failed to stop application: {e}")

print("🎉 All camera override tests completed successfully!")