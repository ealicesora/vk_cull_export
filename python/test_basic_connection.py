#!/usr/bin/env python3
"""Basic connectivity test for VK2Torch without CUDA dependencies"""

import socket
import struct
import json
import os
import sys

def test_basic_connection():
    """Test basic UDS connection and handshake without CUDA"""
    
    print("Testing basic connectivity to Vulkan application...")
    
    # Check if socket exists
    socket_path = "/tmp/vk2torch.sock"
    if not os.path.exists(socket_path):
        print(f"ERROR: Socket {socket_path} does not exist. Is the Vulkan app running with --uds?")
        return False
    
    # Try to connect
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        print(f"✓ Connected to {socket_path}")
    except Exception as e:
        print(f"ERROR: Failed to connect: {e}")
        return False
    
    # Try to receive handshake
    try:
        # Read JSON size
        size_data = client.recv(4)
        if len(size_data) != 4:
            print(f"ERROR: Expected 4 bytes for size, got {len(size_data)}")
            return False
        
        json_size = struct.unpack('I', size_data)[0]
        print(f"✓ Received JSON size: {json_size} bytes")
        
        # Read JSON data
        json_data = client.recv(json_size)
        if len(json_data) != json_size:
            print(f"ERROR: Expected {json_size} bytes, got {len(json_data)}")
            return False
        
        # Parse JSON
        handshake = json.loads(json_data.decode())
        print(f"✓ Received handshake info:")
        print(f"  - Width: {handshake['w']}")
        print(f"  - Height: {handshake['h']}")
        print(f"  - Format: {handshake['format']}")
        print(f"  - Color buffer size: {handshake['color_readback_bytes']} bytes")
        print(f"  - Camera buffer size: {handshake['cam_bytes']} bytes")
        
        # Receive file descriptors (even though we can't use them without CUDA)
        # Create a dummy byte to receive with SCM_RIGHTS
        dummy_buf = bytearray(1)
        fds = []
        ancdata_size = socket.CMSG_SPACE(4 * 4)  # 4 FDs
        
        msg, ancdata, flags, addr = client.recvmsg(1, ancdata_size)
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                # Extract file descriptors
                num_fds = len(cmsg_data) // 4
                for i in range(num_fds):
                    fd = struct.unpack('i', cmsg_data[i*4:(i+1)*4])[0]
                    fds.append(fd)
        
        print(f"✓ Received {len(fds)} file descriptors via SCM_RIGHTS")
        
        # Close FDs since we can't use them without CUDA
        for fd in fds:
            os.close(fd)
        
        client.close()
        print("\n✓ Basic connectivity test PASSED!")
        return True
        
    except Exception as e:
        print(f"ERROR during handshake: {e}")
        import traceback
        traceback.print_exc()
        client.close()
        return False

if __name__ == "__main__":
    success = test_basic_connection()
    sys.exit(0 if success else 1)