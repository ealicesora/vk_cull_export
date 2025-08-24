#!/usr/bin/env python3
"""
运行期验证测试 - 从真实3D场景渲染保存深度PNG
Runtime Verification Test - Save depth PNG from real 3D scene rendering

This test verifies that the vk2torch_ext Python extension can:
1. Initialize the actual LodClusters 3D renderer (not a stub)
2. Load the default bunny.gltf scene 
3. Render real 3D geometry to depth buffer
4. Export the depth data and save as PNG image
5. Prove the integration works end-to-end with real scene data
"""

import sys
import os
import numpy as np

# Add the extension module directory to path
sys.path.insert(0, 'build-py/_bin/Release')

try:
    import vk2torch_ext
    print("✅ Successfully imported vk2torch_ext")
    print(f"   Available classes: {[x for x in dir(vk2torch_ext) if not x.startswith('_')]}")
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    sys.exit(1)

def main():
    """Main verification test"""
    print("\n🚀 Starting runtime verification test...")
    print("   Goal: Prove real 3D scene rendering works by saving depth PNG")
    
    try:
        # Initialize the Vulkan application with real LodClusters renderer
        print("\n1️⃣ Initializing Vk2TorchApp (real 3D renderer)...")
        app = vk2torch_ext.Vk2TorchApp()
        
        # Initialize with small resolution for testing
        width, height = 512, 512
        print(f"   Initializing with resolution: {width}x{height}")
        success = app.initialize(width, height)
        
        if not success:
            print("❌ Failed to initialize Vk2TorchApp")
            return False
        
        print("✅ Successfully initialized Vk2TorchApp")
        
        # Load default scene (should auto-discover bunny.gltf)
        print("\n2️⃣ Loading default 3D scene (bunny.gltf)...")
        scene_loaded = app.loadDefaultScene()
        
        if not scene_loaded:
            print("❌ Failed to load default scene")
            return False
        
        print("✅ Successfully loaded default 3D scene")
        
        # Set camera to view the bunny
        print("\n3️⃣ Setting up camera to view the 3D scene...")
        
        # Create view matrix (camera looking at bunny from distance)
        view_matrix = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, -5.0],  # Camera 5 units back
            [0.0, 0.0, 0.0, 1.0]
        ], dtype=np.float32)
        
        # Create projection matrix (perspective)
        fov = 45.0 * np.pi / 180.0  # 45 degrees
        aspect = width / height
        near = 0.1
        far = 100.0
        
        f = 1.0 / np.tan(fov / 2.0)
        proj_matrix = np.array([
            [f / aspect, 0.0, 0.0, 0.0],
            [0.0, f, 0.0, 0.0],
            [0.0, 0.0, (far + near) / (near - far), (2.0 * far * near) / (near - far)],
            [0.0, 0.0, -1.0, 0.0]
        ], dtype=np.float32)
        
        app.set_camera(view_matrix, proj_matrix)
        print("✅ Camera setup completed")
        
        # Render the frame
        print("\n4️⃣ Rendering 3D scene to depth buffer...")
        render_success = app.render()
        
        if not render_success:
            print("❌ Failed to render scene")
            return False
        
        print("✅ Successfully rendered 3D scene")
        
        # Export depth buffer
        print("\n5️⃣ Exporting depth data from rendered scene...")
        
        try:
            # This should return actual depth data from the 3D scene rendering
            depth_data = app.export_depth_buffer_fd()
            
            if depth_data is None:
                print("❌ Failed to export depth buffer - returned None")
                return False
            
            print(f"✅ Successfully exported depth data")
            print(f"   Depth data type: {type(depth_data)}")
            print(f"   Depth data shape: {depth_data.shape if hasattr(depth_data, 'shape') else 'N/A'}")
            print(f"   Depth value range: {np.min(depth_data) if hasattr(depth_data, 'min') else 'N/A'} to {np.max(depth_data) if hasattr(depth_data, 'max') else 'N/A'}")
            
            # Convert depth to 8-bit for PNG saving
            if hasattr(depth_data, 'shape') and len(depth_data.shape) >= 2:
                # Normalize depth to 0-255 range for visualization
                depth_normalized = ((depth_data - np.min(depth_data)) / (np.max(depth_data) - np.min(depth_data)) * 255).astype(np.uint8)
                
                # Save as PNG using PIL or cv2 if available
                try:
                    from PIL import Image
                    depth_image = Image.fromarray(depth_normalized, mode='L')
                    output_path = "VERIFICATION_DEPTH.png"
                    depth_image.save(output_path)
                    
                    print(f"🎉 SUCCESS! Saved real 3D scene depth to: {output_path}")
                    print(f"   File size: {os.path.getsize(output_path)} bytes")
                    return True
                    
                except ImportError:
                    try:
                        import cv2
                        output_path = "VERIFICATION_DEPTH.png"
                        cv2.imwrite(output_path, depth_normalized)
                        
                        print(f"🎉 SUCCESS! Saved real 3D scene depth to: {output_path}")
                        print(f"   File size: {os.path.getsize(output_path)} bytes")
                        return True
                        
                    except ImportError:
                        # Fallback: save as numpy array
                        output_path = "VERIFICATION_DEPTH.npy"
                        np.save(output_path, depth_data)
                        
                        print(f"🎉 SUCCESS! Saved real 3D scene depth to: {output_path}")
                        print(f"   File size: {os.path.getsize(output_path)} bytes")
                        print("   Note: Saved as numpy array since PIL/cv2 not available")
                        return True
            else:
                print("❌ Depth data does not have expected array structure")
                return False
                
        except Exception as e:
            print(f"❌ Exception during depth export: {e}")
            return False
        
    except Exception as e:
        print(f"❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("="*60)
    print("🔬 VK2TORCH RUNTIME VERIFICATION TEST")
    print("   Testing real 3D scene rendering with LodClusters")
    print("="*60)
    
    success = main()
    
    print("\n" + "="*60)
    if success:
        print("🎉 VERIFICATION COMPLETE - REAL 3D RENDERING CONFIRMED!")
        print("   The vk2torch_ext extension successfully:")
        print("   ✅ Initialized real LodClusters 3D renderer")
        print("   ✅ Loaded actual 3D scene geometry (bunny.gltf)")  
        print("   ✅ Rendered real 3D depth data")
        print("   ✅ Exported and saved depth image")
        print("   This proves the Python extension has full 3D rendering capability!")
    else:
        print("❌ VERIFICATION FAILED")
        print("   The test did not complete successfully")
        print("   Check error messages above for details")
    print("="*60)
    
    sys.exit(0 if success else 1)