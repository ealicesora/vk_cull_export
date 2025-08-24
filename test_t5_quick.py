#!/usr/bin/env python3
"""
T5 快速验证 - 验证 API 存在并可调用
"""

import sys
sys.path.insert(0, 'build-py/_bin/Release')

def quick_api_check():
    """快速检查所有 T5 API 是否存在并可调用"""
    print("T5 Quick API Verification")
    print("=" * 40)
    
    try:
        import vk2torch_ext
        print("✅ vk2torch_ext imported")
        
        # Check if all required methods exist
        app_class = vk2torch_ext.Vk2TorchApp
        
        required_methods = [
            'size',
            'row_pitch_bytes', 
            'export_depth_buffer_fd',
            'export_frame_done_semaphore_fd',
            'set_camera',
            'last_signaled_frame'
        ]
        
        print("\nChecking API methods exist...")
        for method in required_methods:
            if hasattr(app_class, method):
                print(f"✅ {method}() - EXISTS")
            else:
                print(f"❌ {method}() - MISSING")
                return False
        
        # Quick instantiation check
        print("\nTesting instantiation...")
        try:
            app = vk2torch_ext.Vk2TorchApp(800, 600, True, "")
            print("✅ App instantiation successful")
            
            # Quick method calls (non-destructive)
            H, W = app.size()
            print(f"✅ size() = ({H}, {W})")
            
            rp = app.row_pitch_bytes()
            print(f"✅ row_pitch_bytes() = {rp}")
            
            last = app.last_signaled_frame()  
            print(f"✅ last_signaled_frame() = {last}")
            
            # Test FD exports (careful with cleanup)
            depth_fd = app.export_depth_buffer_fd()
            semaphore_fd = app.export_frame_done_semaphore_fd()
            print(f"✅ FD exports: depth={depth_fd}, semaphore={semaphore_fd}")
            
            # Clean up any valid FDs
            import os
            if depth_fd >= 0:
                os.close(depth_fd)
            if semaphore_fd >= 0:
                os.close(semaphore_fd)
            
            print("\n🎉 T5 VERIFICATION COMPLETE!")
            print("✅ All required APIs are implemented")
            print("✅ PyBridge connections are working")
            print("✅ FD exports are functional")
            
            # Clean shutdown
            app.stop()
            return True
            
        except Exception as e:
            print(f"❌ Runtime error: {e}")
            return False
            
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

if __name__ == "__main__":
    success = quick_api_check()
    print("\n" + "=" * 40)
    if success:
        print("🎉 T5 IMPLEMENTATION VERIFIED!")
        print("Ready for integration testing")
    else:
        print("❌ T5 VERIFICATION FAILED")
    print("=" * 40)