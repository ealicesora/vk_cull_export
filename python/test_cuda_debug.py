#!/usr/bin/env python3
"""Debug CUDA external memory issues"""

import ctypes
import ctypes.util
import os

# CUDA constants
CUDA_SUCCESS = 0
CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD = 0x1

def test_cuda_basics():
    """Test basic CUDA loading and initialization"""
    
    # Load CUDA
    libcuda_name = ctypes.util.find_library('cuda')
    if not libcuda_name:
        for path in ['/usr/local/cuda/lib64/libcuda.so', '/usr/lib/x86_64-linux-gnu/libcuda.so']:
            if os.path.exists(path):
                libcuda_name = path
                break
    
    if not libcuda_name:
        print("ERROR: CUDA library not found")
        return False
        
    print(f"Found CUDA library: {libcuda_name}")
    cuda = ctypes.CDLL(libcuda_name)
    
    # Initialize CUDA
    result = cuda.cuInit(0)
    print(f"cuInit result: {result}")
    if result != CUDA_SUCCESS:
        return False
    
    # Get device count
    count = ctypes.c_int()
    result = cuda.cuDeviceGetCount(ctypes.byref(count))
    print(f"cuDeviceGetCount result: {result}, count: {count.value}")
    
    # Get current context
    ctx = ctypes.c_void_p()
    result = cuda.cuCtxGetCurrent(ctypes.byref(ctx))
    print(f"cuCtxGetCurrent result: {result}, ctx: {ctx.value}")
    
    if not ctx.value:
        # Create context
        device = ctypes.c_int(0)
        result = cuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, device)
        print(f"cuCtxCreate_v2 result: {result}")
        if result != CUDA_SUCCESS:
            return False
    
    # Check if external memory functions exist
    try:
        cuImportExternalMemory = cuda.cuImportExternalMemory
        print("✓ cuImportExternalMemory found")
    except AttributeError:
        print("✗ cuImportExternalMemory NOT found - CUDA version too old?")
        return False
    
    # Check CUDA version
    version = ctypes.c_int()
    result = cuda.cuDriverGetVersion(ctypes.byref(version))
    major = version.value // 1000
    minor = (version.value % 1000) // 10
    print(f"CUDA Driver version: {major}.{minor}")
    
    # Test importing a dummy FD (this will fail but we can check the error)
    print("\nTesting external memory import with dummy FD...")
    
    # Define the structure properly
    class CUDA_EXTERNAL_MEMORY_HANDLE_DESC(ctypes.Structure):
        class Handle(ctypes.Union):
            _fields_ = [
                ("fd", ctypes.c_int),
                ("win32", ctypes.c_void_p),
                ("nvSciBufObject", ctypes.c_void_p),
            ]
        
        _fields_ = [
            ("type", ctypes.c_uint),
            ("handle", Handle),
            ("size", ctypes.c_ulonglong),
            ("flags", ctypes.c_uint),
            ("reserved", ctypes.c_uint * 16),
        ]
    
    desc = CUDA_EXTERNAL_MEMORY_HANDLE_DESC()
    desc.type = CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD
    desc.handle.fd = -1  # Invalid FD for testing
    desc.size = 4096
    desc.flags = 0
    
    ext_mem = ctypes.c_void_p()
    cuda.cuImportExternalMemory.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(CUDA_EXTERNAL_MEMORY_HANDLE_DESC)]
    cuda.cuImportExternalMemory.restype = ctypes.c_int
    
    result = cuda.cuImportExternalMemory(ctypes.byref(ext_mem), ctypes.byref(desc))
    print(f"cuImportExternalMemory with invalid FD result: {result}")
    print("  Expected: non-zero error code (since FD is invalid)")
    print(f"  Error codes: 1=CUDA_ERROR_INVALID_VALUE, 999=CUDA_ERROR_INVALID_HANDLE")
    
    return True

if __name__ == "__main__":
    success = test_cuda_basics()
    print(f"\nCUDA basic test: {'PASSED' if success else 'FAILED'}")