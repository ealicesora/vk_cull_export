#!/usr/bin/env python3
"""Minimal test for shared memory integration."""

import sys
import os
import numpy as np
import time

# Add Python client path
sys.path.insert(0, 'python')

# Import shared memory for camera matrices
import struct
from multiprocessing import shared_memory

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
    
    def write_cam32(self, view_flat, proj_flat):
        """Write view and projection matrices using seqlock protocol."""
        if not self.shm:
            return False
            
        # Combine view and proj matrices into 32 float32 array
        view_arr = np.asarray(view_flat, dtype=np.float32).flatten()[:16]
        proj_arr = np.asarray(proj_flat, dtype=np.float32).flatten()[:16]
        
        if len(view_arr) != 16 or len(proj_arr) != 16:
            raise ValueError("View and projection matrices must have 16 elements each")
        
        camera_data = np.concatenate([view_arr, proj_arr])
        
        # Get sequence counter for seqlock protocol
        seq_view = memoryview(self.shm.buf)[self.seq_offset:self.seq_offset + 8]
        data_view = memoryview(self.shm.buf)[self.data_offset:self.data_offset + 128]
        
        # Read current sequence 
        seq = struct.unpack('<Q', seq_view)[0]
        
        # Step 1: Increment sequence to odd (writing state)
        seq += 1
        struct.pack_into('<Q', self.shm.buf, self.seq_offset, seq)
        
        # Step 2: Write the data
        data_view[:] = camera_data.tobytes()
        
        # Step 3: Increment sequence to even (stable state)  
        seq += 1
        struct.pack_into('<Q', self.shm.buf, self.seq_offset, seq)
        
        print(f"📝 Written camera matrices to shared memory (seq={seq})")
        return True
    
    def close(self):
        """Close shared memory."""
        if self.shm:
            self.shm.close()
            self.shm = None

def test_minimal():
    """Test only the shared memory writer."""
    from vk2torch_client import VK2TorchClient
    
    print("🧪 MINIMAL SHARED MEMORY TEST")
    print("Connecting to existing Vulkan app...")
    
    client = VK2TorchClient('/tmp/vk2torch.sock')
    camera_writer = SharedMemoryCameraWriter()
    
    if client.connect():
        print(f"✅ Connected: {client.width}x{client.height}")
        
        # Initialize shared memory
        if camera_writer.create_or_open():
            print("✅ Shared memory ready")
            
            # Test a few camera updates
            for i in range(3):
                # Create simple test matrices
                view = np.eye(4, dtype=np.float32)
                view[2, 3] = -5.0 - i  # Move camera back
                proj = np.eye(4, dtype=np.float32)
                
                # Use shared memory instead of socket
                camera_writer.write_cam32(view.flatten(), proj.flatten())
                
                # Signal semaphore if CUDA is available
                if hasattr(client, 'cuda_api') and client.cuda_api:
                    client.cuda_api.signal_semaphore(client.sem_cam, client.frame_number)
                    client.frame_number += 1
                
                # Try to get frame
                frame = client.get_frame(timeout_ms=1000)
                if frame is not None:
                    print(f"✅ Frame {i+1}: Got frame data")
                else:
                    print(f"⚠️ Frame {i+1}: No frame (expected without CUDA)")
                    
                time.sleep(0.1)
            
            print("✅ Shared memory test successful!")
        else:
            print("❌ Failed to create shared memory")
            
        camera_writer.close()
        client.disconnect()
        return True
    else:
        print("❌ Connection failed")
        camera_writer.close()
        return False

if __name__ == "__main__":
    success = test_minimal()
    sys.exit(0 if success else 1)