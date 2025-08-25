#!/usr/bin/env python3
"""
Test script for the new three-part headless system in VK2Torch extension.

Usage:
    cd build-py/_bin/Release
    python ../../../test_headless_three_part.py
"""

import sys
import os

# Add current directory to path for vk2torch_ext import
sys.path.insert(0, os.getcwd())

try:
    import vk2torch_ext
    print("✅ Successfully imported vk2torch_ext")
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    print("Make sure you're running from build-py/_bin/Release directory")
    sys.exit(1)

def test_three_part_headless():
    """Test the new three-part headless system"""
    print("\n🧪 Testing three-part headless system...")
    
    try:
        # Create VK2Torch app
        print("Creating Vk2TorchApp...")
        app = vk2torch_ext.Vk2TorchApp(
            width=512, 
            height=512, 
            raster=True,
            scene_path="bunny.gltf",  # Will search for this automatically
            asset_root=""  # Will auto-detect
        )
        print("✅ Vk2TorchApp created successfully")
        
        # Test the three-part system
        print("\n--- Three-Part Headless System Test ---")
        
        # Step 1: Initialize
        print("1. Calling headless_init()...")
        init_result = app.headless_init()
        print(f"   headless_init() returned: {init_result}")
        
        # Step 2: Render some frames
        print("2. Rendering frames with headless_step()...")
        frame_count = 0
        max_frames = 5  # Render 5 frames for test
        
        while frame_count < max_frames:
            step_result = app.headless_step()
            frame_count += 1
            print(f"   Frame {frame_count}: headless_step() returned {step_result}")
            
            if not step_result:
                print(f"   headless_step() returned False after {frame_count} frames")
                break
        
        # Step 3: Shutdown
        print("3. Calling headless_shutdown()...")
        app.headless_shutdown()
        print("   headless_shutdown() completed")
        
        print("\n✅ Three-part headless system test completed successfully!")
        
        # Cleanup
        app.stop()
        print("✅ App stopped successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("🚀 VK2Torch Three-Part Headless System Test")
    print("=" * 50)
    
    success = test_three_part_headless()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())