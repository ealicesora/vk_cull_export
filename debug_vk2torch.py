#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'build-py', '_bin', 'Release'))

print("Starting debug test...")

try:
    import vk2torch_ext
    print("✅ Extension imported successfully")
    
    print("Available objects:", dir(vk2torch_ext))
    print("Creating Vk2TorchApp with debug output...")
    
    # Try with minimal size first
    app = vk2torch_ext.Vk2TorchApp(128, 128, True)
    print("✅ App created successfully!")
    
    size = app.size()
    print(f"✅ Size: {size}")
    
    app.stop()
    print("✅ App stopped successfully")
    
except Exception as e:
    print(f"❌ Exception: {e}")
    import traceback
    traceback.print_exc()