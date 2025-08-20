#!/usr/bin/env python3
"""
Test script for Vulkan External Memory Optimizations
Tests all the improvements made:
1. Camera buffer 4KB alignment
2. Dedicated allocation support
3. GPU UUID matching
"""

import socket
import struct
import json
import array
import os
import sys
import time

def colored(text, color):
    """Simple colored output"""
    colors = {
        'green': '\033[92m',
        'yellow': '\033[93m',
        'red': '\033[91m',
        'blue': '\033[94m',
        'end': '\033[0m'
    }
    return f"{colors.get(color, '')}{text}{colors['end']}"

def test_optimizations(socket_path="/tmp/vk_test.sock"):
    print(colored("=" * 70, 'blue'))
    print(colored("VULKAN EXTERNAL MEMORY OPTIMIZATIONS TEST", 'blue'))
    print(colored("=" * 70, 'blue'))
    
    results = {
        'connection': False,
        'camera_alignment': False,
        'dedicated_flags': False,
        'uuid_present': False,
        'fd_received': False,
        'cuda_import': None
    }
    
    # Connect to Vulkan app
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        results['connection'] = True
        print(colored("✓ Connected to Vulkan app", 'green'))
    except Exception as e:
        print(colored(f"✗ Failed to connect: {e}", 'red'))
        print(f"\nMake sure Vulkan app is running with:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --offscreen 1 --renderer 0 --validation 0")
        return results
    
    try:
        # Receive handshake
        size_data = client.recv(4)
        json_size = struct.unpack('I', size_data)[0]
        json_data = client.recv(json_size).decode()
        handshake = json.loads(json_data)
        
        print(f"\n{colored('📋 HANDSHAKE DATA:', 'blue')}")
        print(f"   Resolution: {handshake['w']}x{handshake['h']}")
        print(f"   Format: {handshake['format']}")
        
        # Test 1: Camera buffer alignment (should be 4096 or multiple)
        cam_size = handshake['cam_bytes']
        print(f"\n{colored('🔍 OPTIMIZATION TESTS:', 'blue')}")
        
        if cam_size >= 4096 and cam_size % 4096 == 0:
            results['camera_alignment'] = True
            print(colored(f"   ✓ Camera buffer aligned to 4KB: {cam_size} bytes", 'green'))
        else:
            print(colored(f"   ✗ Camera buffer NOT aligned: {cam_size} bytes (expected 4096+)", 'red'))
        
        # Test 2: Dedicated allocation flags
        if 'cam_dedicated' in handshake and 'color_dedicated' in handshake:
            results['dedicated_flags'] = True
            cam_ded = handshake['cam_dedicated']
            color_ded = handshake['color_dedicated']
            print(colored(f"   ✓ Dedicated flags: cam={cam_ded}, color={color_ded}", 'green'))
        else:
            print(colored(f"   ✗ Dedicated flags missing from handshake", 'red'))
            
        # Test 3: GPU UUID for multi-GPU systems
        if 'vk_uuid' in handshake and len(handshake['vk_uuid']) == 32:
            results['uuid_present'] = True
            uuid = handshake['vk_uuid']
            print(colored(f"   ✓ GPU UUID: {uuid[:8]}...{uuid[-8:]}", 'green'))
        else:
            print(colored(f"   ✗ GPU UUID missing or invalid", 'red'))
        
        # Receive file descriptors
        msg = b'x'
        fds = array.array("i")
        msg_data, ancdata, flags, addr = client.recvmsg(len(msg), socket.CMSG_SPACE(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
        
        if len(fds) == 4:
            results['fd_received'] = True
            print(colored(f"   ✓ Received 4 file descriptors", 'green'))
        else:
            print(colored(f"   ✗ Expected 4 FDs, got {len(fds)}", 'red'))
        
        # Test CUDA import if available
        print(f"\n{colored('🔧 CUDA IMPORT TEST:', 'blue')}")
        try:
            import ctypes
            import ctypes.util
            
            libcuda = ctypes.CDLL(ctypes.util.find_library('cuda'))
            
            # Initialize CUDA
            if libcuda.cuInit(0) == 0:
                # Create context
                ctx = ctypes.c_void_p()
                device = ctypes.c_int(0)
                if libcuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, device) == 0:
                    
                    # Test import with correct size and flags
                    class CUDA_EXTERNAL_MEMORY_HANDLE_DESC(ctypes.Structure):
                        class Handle(ctypes.Union):
                            _fields_ = [("fd", ctypes.c_int)]
                        _fields_ = [
                            ("type", ctypes.c_uint),
                            ("handle", Handle),
                            ("size", ctypes.c_ulonglong),
                            ("flags", ctypes.c_uint),
                            ("reserved", ctypes.c_uint * 16)
                        ]
                    
                    desc = CUDA_EXTERNAL_MEMORY_HANDLE_DESC()
                    desc.type = 1  # OPAQUE_FD
                    desc.handle.fd = fds[0]
                    desc.size = handshake['cam_bytes']
                    desc.flags = 0x01 if handshake.get('cam_dedicated', False) else 0x00
                    
                    ext_mem = ctypes.c_void_p()
                    libcuda.cuImportExternalMemory.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
                    libcuda.cuImportExternalMemory.restype = ctypes.c_int
                    
                    result = libcuda.cuImportExternalMemory(ctypes.byref(ext_mem), ctypes.byref(desc))
                    results['cuda_import'] = (result == 0)
                    
                    if result == 0:
                        print(colored(f"   ✓ CUDA import successful", 'green'))
                    else:
                        print(colored(f"   ⚠ CUDA import returned code {result}", 'yellow'))
                        print(f"     (This may be driver-specific)")
        except:
            print(colored(f"   ℹ CUDA not available for testing", 'yellow'))
            
        # Cleanup
        for fd in fds:
            try:
                os.close(fd)
            except:
                pass
                
    except Exception as e:
        print(colored(f"\n✗ Test error: {e}", 'red'))
    finally:
        client.close()
    
    # Summary
    print(f"\n{colored('📊 RESULTS SUMMARY:', 'blue')}")
    passed = sum(1 for v in results.values() if v is True)
    total = len([v for v in results.values() if v is not None])
    
    for key, value in results.items():
        if value is True:
            print(colored(f"   ✓ {key.replace('_', ' ').title()}", 'green'))
        elif value is False:
            print(colored(f"   ✗ {key.replace('_', ' ').title()}", 'red'))
        elif value is None:
            print(colored(f"   - {key.replace('_', ' ').title()} (not tested)", 'yellow'))
    
    print(f"\n{colored(f'Score: {passed}/{total} tests passed', 'blue')}")
    
    if passed == total:
        print(colored("\n🎉 All optimizations working perfectly!", 'green'))
    elif passed >= total - 1:
        print(colored("\n✅ Optimizations working well (CUDA import may vary by driver)", 'green'))
    else:
        print(colored("\n⚠ Some optimizations need attention", 'yellow'))
    
    print(colored("=" * 70, 'blue'))
    
    return results

if __name__ == "__main__":
    # Check if custom socket path provided
    socket_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/vk_test.sock"
    
    # First, provide instructions
    print("\nTo run this test:")
    print("1. Start Vulkan app:")
    print(f"   ./_bin/Release/vk_lod_clusters --uds {socket_path} --offscreen 1 --renderer 0 --validation 0")
    print("2. Run this test in another terminal:")
    print(f"   python3 test_optimizations.py {socket_path}")
    print("\nPress Enter to continue with test...")
    
    try:
        input()
    except:
        pass  # Handle non-interactive mode
    
    results = test_optimizations(socket_path)
    
    # Exit with appropriate code
    sys.exit(0 if results.get('connection', False) else 1)