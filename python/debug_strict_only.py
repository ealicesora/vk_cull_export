#!/usr/bin/env python3
"""
Debug ONLY the strict client semaphore import
"""

import os
import sys
import subprocess
import time
import ctypes
from pathlib import Path

def test_strict_only():
    """Test only the strict client semaphore import."""
    socket_path = "/tmp/debug_strict.sock"
    
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
    
    print("Starting Vulkan app for strict client test...")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(2)
    
    try:
        print("\n=== TESTING STRICT CLIENT WITH STEP-BY-STEP DEBUG ===")
        import vk2torch_client_strict
        import socket
        import struct
        import json
        import array
        
        # Manual connection
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        print("✅ STRICT: Socket connected")
        
        # Receive handshake
        json_size_data = sock.recv(4)
        json_size = struct.unpack('I', json_size_data)[0]
        json_data = sock.recv(json_size)
        handshake = json.loads(json_data.decode())
        print(f"✅ STRICT: Handshake - {handshake['w']}x{handshake['h']}")
        
        # Receive FDs
        msg = b'x'
        fds = array.array("i")
        msg_data, ancdata, flags, addr = sock.recvmsg(len(msg), socket.CMSG_SPACE(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
        
        cam_fd, color_fd, cam_sem_fd, done_sem_fd = fds
        print(f"✅ STRICT: FDs received - cam_sem:{cam_sem_fd}, done_sem:{done_sem_fd}")
        
        # Check FD validity
        for fd_name, fd in [("cam_sem", cam_sem_fd), ("done_sem", done_sem_fd)]:
            try:
                fd_path = f"/proc/self/fd/{fd}"
                if os.path.exists(fd_path):
                    target = os.readlink(fd_path)
                    print(f"✅ FD {fd_name}({fd}) -> {target}")
                else:
                    print(f"❌ FD {fd_name}({fd}) not found")
            except Exception as e:
                print(f"❌ FD {fd_name}({fd}) check failed: {e}")
        
        # Initialize CUDA API
        cuda_api = vk2torch_client_strict.CUDADriverAPI()
        print("✅ STRICT: CUDA API initialized")
        
        device_id = cuda_api.find_device_by_uuid(handshake['vk_uuid'])
        cuda_api.create_context_on_device(device_id)
        print("✅ STRICT: CUDA context created")
        
        # Test semaphore import with maximum debugging
        for sem_name, sem_fd in [("camera", cam_sem_fd), ("done", done_sem_fd)]:
            print(f"\\n=== IMPORTING {sem_name.upper()} SEMAPHORE (FD: {sem_fd}) ===")
            
            # Create descriptor exactly as in working client
            desc = vk2torch_client_strict.CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
            ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
            desc.type = 9
            desc.handle.fd = sem_fd
            desc.flags = 0x00
            
            print(f"  Descriptor size: {ctypes.sizeof(desc)} bytes")
            print(f"  Type: {desc.type}")
            print(f"  FD: {desc.handle.fd}")
            print(f"  Flags: {desc.flags:#04x}")
            
            # Verify structure matches working client
            import vk2torch_client
            orig_desc = vk2torch_client.CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
            print(f"  Size comparison - strict:{ctypes.sizeof(desc)}, orig:{ctypes.sizeof(orig_desc)}, match:{ctypes.sizeof(desc) == ctypes.sizeof(orig_desc)}")
            
            # Try import
            ext_sem = ctypes.c_void_p()
            try:
                print(f"  Calling cuImportExternalSemaphore...")
                result = cuda_api.cuda.cuImportExternalSemaphore(ctypes.byref(ext_sem), ctypes.byref(desc))
                
                if result == 0:
                    print(f"  ✅ SUCCESS! Handle: {ext_sem}")
                else:
                    print(f"  ❌ FAILED with code: {result}")
                    
                    # Get detailed error
                    try:
                        errStr = ctypes.c_char_p()
                        cuda_api.cuda.cuGetErrorString(ctypes.c_int(result), ctypes.byref(errStr))
                        error_msg = errStr.value.decode() if errStr.value else "Unknown"
                        print(f"     Error: {error_msg}")
                    except Exception:
                        print("     Could not get error string")
                        
                    # Check common failure reasons
                    if result == 1:
                        print("     Error code 1 = CUDA_ERROR_INVALID_VALUE")
                        print("     Possible causes:")
                        print("       - Invalid descriptor structure")
                        print("       - Invalid FD")
                        print("       - Wrong semaphore type")
                        print("       - Context/device mismatch")
                        
            except Exception as e:
                print(f"  ❌ EXCEPTION: {e}")
                import traceback
                traceback.print_exc()
        
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
    test_strict_only()