#!/usr/bin/env python3
"""
Simple verification script to test if C++ can read our shared memory data.
"""

import time
import numpy as np
import subprocess
from multiprocessing import shared_memory
from pathlib import Path

def create_test_data():
    """Create shared memory with test pattern."""
    # Create shared memory
    try:
        shm = shared_memory.SharedMemory(name='py2vk_cam32f', create=True, size=256)
        print("✅ Created shared memory")
    except FileExistsError:
        shm = shared_memory.SharedMemory(name='py2vk_cam32f', create=False, size=256)  
        print("✅ Opened existing shared memory")
    
    # Clear it first
    shm.buf[:] = b'\x00' * 256
    
    # Write test pattern: sequence=2 (even, stable), data=0,1,2,3,...,31
    import struct
    
    # Write sequence = 2 at offset 0
    struct.pack_into('<Q', shm.buf, 0, 2)
    
    # Write test pattern at offset 64 (32 floats)
    test_data = np.arange(32, dtype=np.float32)
    test_data.tobytes()
    shm.buf[64:64+128] = test_data.tobytes()
    
    print(f"✅ Written test pattern to shared memory")
    print(f"   Sequence: {struct.unpack('<Q', shm.buf[0:8])[0]}")
    print(f"   First 4 values: {test_data[:4]}")
    
    return shm

def main():
    print("🧪 Creating shared memory with test pattern...")
    shm = create_test_data()
    
    print("\n🚀 Starting Vulkan app to test reading...")
    
    # Start Vulkan app with simple setup
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", "/tmp/verify_shm.sock",
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    try:
        # Run for a few seconds to let it read the shared memory
        process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
        
        print("✅ Vulkan app started. Check logs above for shared memory read results.")
        print("   Look for 'Successfully opened shared memory' and camera matrix values")
        
        time.sleep(3)  # Let it run briefly
        
        process.terminate()
        process.wait()
        
        print("\n✅ Test complete. Check the logs above to verify shared memory reading.")
        
    except Exception as e:
        print(f"❌ Error running Vulkan app: {e}")
    
    finally:
        # Cleanup
        if shm:
            shm.close()
            shm.unlink()
        print("🧹 Cleaned up shared memory")

if __name__ == "__main__":
    main()