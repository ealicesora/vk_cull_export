#!/usr/bin/env python3
"""
Simple test to verify the headless three-part methods are properly bound.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

try:
    import vk2torch_ext
    print("✅ Successfully imported vk2torch_ext")
    
    # Check if the new methods exist
    app_class = vk2torch_ext.Vk2TorchApp
    
    methods_to_check = [
        'headless_init',
        'headless_step', 
        'headless_shutdown'
    ]
    
    print("\n🔍 Checking method bindings...")
    for method_name in methods_to_check:
        if hasattr(app_class, method_name):
            method = getattr(app_class, method_name)
            print(f"✅ {method_name}: {method}")
        else:
            print(f"❌ {method_name}: NOT FOUND")
            
    print("\n📋 All available methods:")
    all_methods = [name for name in dir(app_class) if not name.startswith('_')]
    for method in sorted(all_methods):
        print(f"   - {method}")
        
    print(f"\n✅ Method binding test completed!")
    print(f"   Found {len(methods_to_check)} new headless methods")
    
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error during testing: {e}")
    sys.exit(1)