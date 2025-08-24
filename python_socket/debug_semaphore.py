#!/usr/bin/env python3
"""
Debug semaphore import issue in strict client
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def test_semaphore_debug():
    """Debug the specific semaphore import issue."""
    socket_path = "/tmp/debug_sem.sock"
    
    # Start Vulkan app
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--offscreen", "1",
        "--renderer", "0", 
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("Starting Vulkan app...")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(2)
    
    try:
        # Test original working client first
        print("\n=== TESTING ORIGINAL CLIENT ===")
        import vk2torch_client
        
        with vk2torch_client.VK2TorchClient(socket_path) as orig_client:
            if orig_client.connect():
                print("✅ ORIGINAL: Connected successfully")
                print(f"✅ ORIGINAL: CUDA available: {orig_client.cuda_api is not None}")
                
                if orig_client.cuda_api:
                    print(f"✅ ORIGINAL: Camera sem: {orig_client.sem_cam}")
                    print(f"✅ ORIGINAL: Done sem: {orig_client.sem_done}")
                    print("✅ ORIGINAL: Semaphore import successful")
                else:
                    print("❌ ORIGINAL: No CUDA API")
            else:
                print("❌ ORIGINAL: Connection failed")
        
        # Now test strict client step by step
        print("\n=== TESTING STRICT CLIENT DEBUG ===")
        import vk2torch_client_strict
        
        # Create client
        strict_client = vk2torch_client_strict.VK2TorchClientStrict(socket_path)
        print("✅ STRICT: Client created")
        
        # Try manual connection steps
        import socket
        import struct
        import json
        import array
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        print("✅ STRICT: Socket connected")
        
        # Receive handshake
        json_size_data = sock.recv(4)
        json_size = struct.unpack('I', json_size_data)[0]
        json_data = sock.recv(json_size)
        handshake = json.loads(json_data.decode())
        print(f"✅ STRICT: Handshake received - {handshake['w']}x{handshake['h']}")
        
        # Receive FDs
        msg = b'x'
        fds = array.array("i")
        msg_data, ancdata, flags, addr = sock.recvmsg(len(msg), socket.CMSG_SPACE(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
        
        cam_fd, color_fd, cam_sem_fd, done_sem_fd = fds
        print(f"✅ STRICT: FDs received - cam_sem:{cam_sem_fd}, done_sem:{done_sem_fd}")
        
        # Initialize CUDA API
        cuda_api = vk2torch_client_strict.CUDADriverAPI()
        print("✅ STRICT: CUDA API initialized")
        
        # Find device and create context 
        device_id = cuda_api.find_device_by_uuid(handshake['vk_uuid'])
        cuda_api.create_context_on_device(device_id)
        print("✅ STRICT: CUDA context created")
        
        # Try importing semaphore with detailed debugging
        print(f"\\n=== ATTEMPTING SEMAPHORE IMPORT (FD: {cam_sem_fd}) ===")
        
        # Create descriptor
        desc = vk2torch_client_strict.CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
        import ctypes
        ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
        desc.type = 9
        desc.handle.fd = cam_sem_fd
        desc.flags = 0x00
        
        print(f"Descriptor size: {ctypes.sizeof(desc)}")
        print(f"Descriptor type: {desc.type}")
        print(f"Descriptor fd: {desc.handle.fd}")
        print(f"Descriptor flags: {desc.flags:#04x}")
        
        # Check FD validity
        try:
            fd_path = f"/proc/self/fd/{cam_sem_fd}"
            if os.path.exists(fd_path):
                target = os.readlink(fd_path)
                print(f"FD {cam_sem_fd} -> {target}")
            else:
                print(f"❌ FD {cam_sem_fd} not found in /proc/self/fd/")
        except Exception as e:
            print(f"❌ FD check failed: {e}")
        
        # Try the actual import
        ext_sem = ctypes.c_void_p()
        try:
            result = cuda_api.cuda.cuImportExternalSemaphore(ctypes.byref(ext_sem), ctypes.byref(desc))
            if result == 0:
                print("✅ STRICT: Semaphore import SUCCESSFUL!")
                print(f"✅ External semaphore handle: {ext_sem}")
            else:
                print(f"❌ STRICT: cuImportExternalSemaphore failed with code: {result}")
                
                # Try to get error string
                try:
                    errStr = ctypes.c_char_p()
                    cuda_api.cuda.cuGetErrorString(ctypes.c_int(result), ctypes.byref(errStr))
                    error_msg = errStr.value.decode() if errStr.value else "Unknown"
                    print(f"   Error message: {error_msg}")
                except Exception:
                    print("   Could not get error message")
                    
        except Exception as e:
            print(f"❌ STRICT: Exception during semaphore import: {e}")
        
        # Cleanup FDs
        for fd in fds:
            try:
                os.close(fd)
            except:
                pass
                
        sock.close()
        
    finally:
        # Cleanup
        if vulkan_process:
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    test_semaphore_debug()