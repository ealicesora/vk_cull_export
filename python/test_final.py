#!/usr/bin/env python3
"""
Test script for POSIX shared memory camera matrix transmission.
Replaces JSON/binary socket transmission with shared memory while keeping
existing socket handshake and semaphore synchronization.
"""

import os
import sys
import time
import struct
import socket
import subprocess
from pathlib import Path
from multiprocessing import shared_memory

import numpy as np


class SharedMemoryCameraWriter:
    """POSIX shared memory writer for camera matrices using seqlock protocol."""
    
    def __init__(self, name='py2vk_cam32f'):
        self.name = name
        self.shm = None
        self.seq_offset = 0      # uint64_t seq
        self.data_offset = 64    # float data[32] at 64-byte aligned offset
        self.size = 256          # Total shared memory size
        
    def create_or_open(self):
        """Create or open the shared memory segment."""
        try:
            # Try to create new shared memory
            self.shm = shared_memory.SharedMemory(
                name=self.name, 
                create=True, 
                size=self.size
            )
            print(f"✅ Created shared memory: {self.name}")
            # Initialize with zeros
            self.shm.buf[:] = b'\x00' * self.size
        except FileExistsError:
            # Shared memory already exists, open it
            self.shm = shared_memory.SharedMemory(name=self.name, create=False)
            print(f"✅ Opened existing shared memory: {self.name}")
        
        return self.shm is not None
    
    def write_cam32(self, arr32):
        """Write 32 float32 values using seqlock protocol.
        
        Seqlock protocol:
        1. Increment sequence (make it odd - indicates writing)
        2. Write data
        3. Increment sequence (make it even - indicates stable)
        """
        if not self.shm:
            return False
            
        # Ensure input is correct format
        arr32 = np.asarray(arr32, dtype=np.float32)
        if arr32.shape != (32,):
            raise ValueError(f"Expected 32 float32 values, got shape {arr32.shape}")
        
        # Get sequence counter as memoryview for atomic-like access
        seq_view = memoryview(self.shm.buf)[self.seq_offset:self.seq_offset + 8]
        data_view = memoryview(self.shm.buf)[self.data_offset:self.data_offset + 128]
        
        # Read current sequence 
        seq = struct.unpack('<Q', seq_view)[0]
        
        # Step 1: Increment sequence to odd (writing state)
        seq += 1
        struct.pack_into('<Q', self.shm.buf, self.seq_offset, seq)
        
        # Step 2: Write the data
        arr32.tobytes(order='C')  # Ensure C-contiguous
        data_view[:] = arr32.tobytes()
        
        # Step 3: Increment sequence to even (stable state)  
        seq += 1
        struct.pack_into('<Q', self.shm.buf, self.seq_offset, seq)
        
        return True
    
    def close(self):
        """Close shared memory (but don't unlink - let C++ side handle that)."""
        if self.shm:
            self.shm.close()
            self.shm = None


class VK2TorchTestClient:
    """Simple test client that uses shared memory for camera data."""
    
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.socket = None
        self.connected = False
        self.width = 0
        self.height = 0
        self.frame_number = 1
        self.camera_writer = SharedMemoryCameraWriter()
        
    def connect(self):
        """Connect to Vulkan app via UDS socket."""
        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(self.socket_path)
            
            # Receive handshake data
            size_data = self.socket.recv(4)
            if len(size_data) != 4:
                return False
                
            json_size = struct.unpack('<I', size_data)[0]
            json_data = self.socket.recv(json_size).decode('utf-8')
            
            print(f"📡 Received handshake: {json_data}")
            
            # Parse basic info (simplified)
            import json
            handshake = json.loads(json_data)
            self.width = handshake['w']
            self.height = handshake['h']
            
            # Receive file descriptors (we don't use them in this test)
            try:
                dummy_msg = self.socket.recv(1)  # Receive the dummy byte with FDs
                print(f"📡 Received FDs via SCM_RIGHTS")
            except Exception as e:
                print(f"⚠️  FD reception: {e}")
            
            # Receive ready message
            size_data = self.socket.recv(4)
            if len(size_data) == 4:
                ready_size = struct.unpack('<I', size_data)[0]
                ready_data = self.socket.recv(ready_size).decode('utf-8')
                print(f"📡 Received ready: {ready_data}")
            
            self.connected = True
            
            # Setup shared memory for camera data
            if not self.camera_writer.create_or_open():
                print("❌ Failed to setup shared memory")
                return False
                
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def update_camera(self, view_matrix, proj_matrix):
        """Update camera using shared memory instead of socket."""
        if not self.connected:
            return False
            
        try:
            # Flatten matrices to 32 float32 array (16 view + 16 proj)
            view_flat = np.asarray(view_matrix, dtype=np.float32).flatten()
            proj_flat = np.asarray(proj_matrix, dtype=np.float32).flatten()
            
            if len(view_flat) != 16 or len(proj_flat) != 16:
                raise ValueError("View and projection matrices must be 4x4")
            
            # Combine into 32-element array
            camera_data = np.concatenate([view_flat, proj_flat])
            
            # Write to shared memory using seqlock
            success = self.camera_writer.write_cam32(camera_data)
            if success:
                print(f"📝 Camera data written to shared memory (frame {self.frame_number})")
                self.frame_number += 1
            
            return success
            
        except Exception as e:
            print(f"❌ Camera update failed: {e}")
            return False
    
    def close(self):
        """Close connection and cleanup."""
        if self.camera_writer:
            self.camera_writer.close()
        if self.socket:
            self.socket.close()
            self.socket = None
        self.connected = False


def create_test_matrices(distance=4.0, yaw=0.0, pitch=0.0):
    """Create simple test view and projection matrices."""
    # Simple orbit camera
    x = distance * np.cos(yaw) * np.cos(pitch)
    y = distance * np.sin(pitch)  
    z = distance * np.sin(yaw) * np.cos(pitch)
    
    # Look-at matrix (simplified)
    view = np.eye(4, dtype=np.float32)
    view[0, 3] = -x
    view[1, 3] = -y  
    view[2, 3] = -z
    
    # Simple projection matrix
    proj = np.eye(4, dtype=np.float32)
    proj[0, 0] = 1.0  # fov scaling
    proj[1, 1] = 1.0
    proj[2, 2] = -1.0
    proj[3, 2] = -1.0
    proj[2, 3] = -2.0
    
    return view, proj


def test_shared_memory_camera():
    """Test the shared memory camera implementation."""
    socket_path = "/tmp/test_shared_cam.sock"
    
    # Start Vulkan app
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--renderer", "0",
        "--validation", "0", 
        "--gridcopies", "1"
    ]
    
    print("🚀 Starting Vulkan app...")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(2)  # Wait for startup
    
    try:
        # Connect to Vulkan app
        client = VK2TorchTestClient(socket_path)
        if not client.connect():
            print("❌ Failed to connect to Vulkan app")
            return False
        
        print(f"✅ Connected! Resolution: {client.width}x{client.height}")
        
        # Test 1: Write test pattern for verification
        print("\n🧪 Test 1: Writing test pattern to shared memory...")
        test_pattern = np.arange(32, dtype=np.float32)
        client.camera_writer.write_cam32(test_pattern)
        print("✅ Test pattern written (first 4 values: 0.0, 1.0, 2.0, 3.0)")
        time.sleep(1)  # Let Vulkan read it
        
        # Test 2: Write real camera matrices
        print("\n🧪 Test 2: Writing camera matrices...")
        for i in range(3):
            distance = 4.0 + i * 0.5
            yaw = i * 0.3
            view, proj = create_test_matrices(distance, yaw)
            
            success = client.update_camera(view, proj)
            if success:
                print(f"✅ Frame {i+1}: Camera updated (distance={distance:.1f}, yaw={yaw:.1f})")
            else:
                print(f"❌ Frame {i+1}: Camera update failed")
            
            time.sleep(0.5)  # Brief pause between frames
        
        print("\n🎉 Shared memory camera test completed!")
        print("Check Vulkan app logs to verify camera data reception.")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if 'client' in locals():
            client.close()
        
        # Cleanup
        vulkan_process.terminate()
        vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    success = test_shared_memory_camera()
    sys.exit(0 if success else 1)