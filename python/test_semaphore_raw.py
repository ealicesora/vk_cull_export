#!/usr/bin/env python3
"""
Raw CUDA semaphore test without CuPy/PyTorch dependencies
"""

import socket
import struct
import json
import array
import os
import sys
import time
import ctypes
import ctypes.util

def test_raw_semaphore():
    print("\n" + "="*60)
    print("RAW CUDA SEMAPHORE SYNCHRONIZATION TEST")
    print("="*60 + "\n")
    
    # Connect to Vulkan app
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect("/tmp/sem_test.sock")
        print("✓ Connected to Vulkan app")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        print("\nStart Vulkan app with:")
        print("  VK2TORCH_TEST_SEMAPHORE=1 ./_bin/Release/vk_lod_clusters \\")
        print("    --uds /tmp/sem_test.sock --offscreen 1 --renderer 0 --validation 0")
        return False
    
    try:
        # Receive handshake
        size_data = client.recv(4)
        json_size = struct.unpack('I', size_data)[0]
        json_data = client.recv(json_size).decode()
        handshake = json.loads(json_data)
        
        print(f"  Resolution: {handshake['w']}x{handshake['h']}")
        print(f"  Camera buffer: {handshake['cam_bytes']} bytes")
        print(f"  Semaphore test enabled: {handshake.get('semaphore_test_enabled', False)}")
        
        # Receive file descriptors
        msg = b'x'
        fds = array.array("i")
        msg_data, ancdata, flags, addr = client.recvmsg(len(msg), socket.CMSG_SPACE(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
        
        cam_fd, color_fd, cam_sem_fd, done_sem_fd = fds
        print(f"✓ Received FDs: cam_sem={cam_sem_fd}, done_sem={done_sem_fd}")
        
        # Initialize CUDA
        try:
            libcuda = ctypes.CDLL(ctypes.util.find_library('cuda'))
            
            # Initialize
            result = libcuda.cuInit(0)
            if result != 0:
                print(f"✗ cuInit failed: {result}")
                return False
            print("✓ CUDA initialized")
            
            # Create context
            ctx = ctypes.c_void_p()
            result = libcuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, 0)
            if result != 0:
                print(f"✗ cuCtxCreate failed: {result}")
                return False
            print("✓ CUDA context created")
            
            # Create stream
            stream = ctypes.c_void_p()
            result = libcuda.cuStreamCreate(ctypes.byref(stream), 0)
            if result != 0:
                print(f"✗ cuStreamCreate failed: {result}")
                return False
            
            # Import semaphores
            class CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC(ctypes.Structure):
                class Handle(ctypes.Union):
                    _fields_ = [("fd", ctypes.c_int)]
                _fields_ = [
                    ("type", ctypes.c_uint),
                    ("handle", Handle),
                    ("flags", ctypes.c_uint),
                    ("reserved", ctypes.c_uint * 16)
                ]
            
            # Import camera semaphore
            desc = CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
            ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
            desc.type = 9  # OPAQUE_FD
            desc.handle.fd = cam_sem_fd
            desc.flags = 0
            
            sem_cam = ctypes.c_void_p()
            libcuda.cuImportExternalSemaphore.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            libcuda.cuImportExternalSemaphore.restype = ctypes.c_int
            
            result = libcuda.cuImportExternalSemaphore(ctypes.byref(sem_cam), ctypes.byref(desc))
            if result != 0:
                print(f"✗ Failed to import camera semaphore: {result}")
                return False
            print("✓ Camera semaphore imported")
            
            # Import done semaphore
            desc.handle.fd = done_sem_fd
            sem_done = ctypes.c_void_p()
            result = libcuda.cuImportExternalSemaphore(ctypes.byref(sem_done), ctypes.byref(desc))
            if result != 0:
                print(f"✗ Failed to import done semaphore: {result}")
                return False
            print("✓ Done semaphore imported")
            
            print("\n--- SEMAPHORE PING-PONG TEST ---")
            
            # Define signal/wait structures
            class CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS(ctypes.Structure):
                class Value(ctypes.Union):
                    _fields_ = [("fence", ctypes.c_ulonglong)]
                _fields_ = [
                    ("params", Value),
                    ("flags", ctypes.c_uint),
                    ("reserved", ctypes.c_uint * 16)
                ]
            
            class CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS(ctypes.Structure):
                class Value(ctypes.Union):
                    _fields_ = [("fence", ctypes.c_ulonglong)]
                _fields_ = [
                    ("params", Value),
                    ("flags", ctypes.c_uint),
                    ("reserved", ctypes.c_uint * 16)
                ]
            
            # Test semaphore echo
            for i in range(5):
                test_value = 42 + i
                
                # Signal camera semaphore
                signal_params = CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS()
                signal_params.params.fence = test_value
                signal_params.flags = 0
                
                libcuda.cuSignalExternalSemaphoresAsync.argtypes = [
                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, 
                    ctypes.c_uint, ctypes.c_void_p
                ]
                libcuda.cuSignalExternalSemaphoresAsync.restype = ctypes.c_int
                
                result = libcuda.cuSignalExternalSemaphoresAsync(
                    ctypes.byref(sem_cam), ctypes.byref(signal_params), 1, stream
                )
                
                if result != 0:
                    print(f"  [{i+1}/5] ✗ Signal failed: {result}")
                    continue
                
                # Synchronize to ensure signal is sent
                libcuda.cuStreamSynchronize(stream)
                
                print(f"  [{i+1}/5] Signaled value {test_value}, waiting for echo...")
                
                # Wait for echo on done semaphore
                wait_params = CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS()
                wait_params.params.fence = test_value
                wait_params.flags = 0
                
                libcuda.cuWaitExternalSemaphoresAsync.argtypes = [
                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                    ctypes.c_uint, ctypes.c_void_p
                ]
                libcuda.cuWaitExternalSemaphoresAsync.restype = ctypes.c_int
                
                start_time = time.time()
                result = libcuda.cuWaitExternalSemaphoresAsync(
                    ctypes.byref(sem_done), ctypes.byref(wait_params), 1, stream
                )
                
                if result != 0:
                    print(f"  [{i+1}/5] ✗ Wait failed: {result}")
                    continue
                
                # Synchronize stream
                result = libcuda.cuStreamSynchronize(stream)
                elapsed = (time.time() - start_time) * 1000
                
                if result == 0:
                    print(f"  [{i+1}/5] ✓ Echo received in {elapsed:.1f}ms")
                else:
                    print(f"  [{i+1}/5] ✗ Stream sync failed: {result}")
                
                time.sleep(0.01)
            
            print("\n✅ SEMAPHORE TEST COMPLETED!")
            
        except Exception as e:
            print(f"✗ CUDA error: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    except Exception as e:
        print(f"✗ Test error: {e}")
        return False
    finally:
        # Cleanup
        for fd in fds:
            try:
                os.close(fd)
            except:
                pass
        client.close()
    
    return True

if __name__ == "__main__":
    # First start Vulkan app
    print("Starting Vulkan app with semaphore test...")
    import subprocess
    
    env = os.environ.copy()
    env['VK2TORCH_TEST_SEMAPHORE'] = '1'
    
    proc = subprocess.Popen(
        ['./_bin/Release/vk_lod_clusters',
         '--uds', '/tmp/sem_test.sock',
         '--offscreen', '1',
         '--renderer', '0',
         '--validation', '0',
         '--gridcopies', '1'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    # Wait for startup
    time.sleep(3)
    
    # Run test
    try:
        success = test_raw_semaphore()
    finally:
        # Cleanup
        proc.terminate()
        proc.wait()
    
    sys.exit(0 if success else 1)