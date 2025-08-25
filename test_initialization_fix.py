#!/usr/bin/env python3
"""
Test to verify the initialization order fix.
We'll capture stdout to see if the debug messages appear in the right order.
"""

import sys
import subprocess
import os
import time

def test_initialization():
    """Test if initialization messages appear in correct order"""
    
    # Change to the correct directory
    os.chdir('/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py/_bin/Release')
    
    # Set up environment
    env = os.environ.copy()
    env['VK2TORCH_DATA_ROOT'] = '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters'
    
    # Test script that should show initialization messages
    test_script = '''
import sys
sys.path.insert(0, ".")
import vk2torch_ext
import threading
import time

print("=== Testing Initialization Order ===")

# Capture any output and run app creation in try/catch
try:
    print("Creating Vk2TorchApp...")
    app = vk2torch_ext.Vk2TorchApp(256, 256, True, "", "/home/gongyuning/Desktop/vk_cull/vk_lod_clusters")
    
    print("App created successfully")
    print("Waiting 3 seconds to see if render thread messages appear...")
    
    # Wait to see if we get the render thread messages
    time.sleep(3)
    
    print("Stopping app...")
    app.stop()
    print("=== SUCCESS: App lifecycle completed ===")
    
except Exception as e:
    print(f"Exception during app creation: {e}")
    print("=== This tells us about the crash location ===")
'''
    
    cmd = ['python', '-c', test_script]
    
    print("Running initialization test...")
    print("Expected messages:")
    print("  - 'Render thread started, running application loop'")
    print("  - 'PyBridge ready, application initialized'")
    print("  - 'Loading default 3D scene...'")
    print("\nActual output:")
    print("=" * 50)
    
    try:
        # Run with timeout to prevent hanging
        result = subprocess.run(cmd, capture_output=True, text=True, 
                              env=env, timeout=10, cwd=os.getcwd())
        
        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")  
        print(result.stderr)
        print("Return code:", result.returncode)
        
        # Check if we see the expected messages
        stdout = result.stdout + result.stderr
        
        if "Render thread started, running application loop" in stdout:
            print("✅ SUCCESS: Render thread start message found!")
        else:
            print("❌ MISSING: Render thread start message")
            
        if "PyBridge ready" in stdout:
            print("✅ SUCCESS: PyBridge ready message found!")
        else:
            print("❌ MISSING: PyBridge ready message")
            
        if "Loading default 3D scene" in stdout:
            print("✅ SUCCESS: Scene loading message found!")
        else:
            print("❌ MISSING: Scene loading message")
            
    except subprocess.TimeoutExpired:
        print("❌ TIMEOUT: Process hung - fix didn't work")
    except Exception as e:
        print(f"❌ ERROR running test: {e}")

if __name__ == "__main__":
    test_initialization()