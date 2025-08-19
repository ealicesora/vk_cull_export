#!/usr/bin/env python3
"""Test if received file descriptors are valid"""

import socket
import struct
import json
import os
import fcntl

def test_fd_validity():
    """Test if FDs received from Vulkan are valid"""
    
    socket_path = "/tmp/vk2torch.sock"
    if not os.path.exists(socket_path):
        print(f"ERROR: Socket {socket_path} does not exist")
        print("Please run: ./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --offscreen 1 --renderer 0 --validation 0")
        return False
    
    # Connect
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(socket_path)
    print(f"Connected to {socket_path}")
    
    # Read handshake
    size_data = client.recv(4)
    json_size = struct.unpack('I', size_data)[0]
    json_data = client.recv(json_size).decode()
    handshake = json.loads(json_data)
    print(f"Handshake received: {handshake['w']}x{handshake['h']}")
    
    # Receive FDs
    msg, ancdata, flags, addr = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
    
    fds = []
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
            num_fds = len(cmsg_data) // 4
            for i in range(num_fds):
                fd = struct.unpack('i', cmsg_data[i*4:(i+1)*4])[0]
                fds.append(fd)
    
    print(f"\nReceived {len(fds)} file descriptors:")
    
    # Check each FD
    for i, fd in enumerate(fds):
        print(f"\nFD[{i}] = {fd}")
        
        # Check if FD is valid using fcntl
        try:
            flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            print(f"  ✓ Valid FD (flags: {flags})")
            
            # Try to get FD status flags
            status = fcntl.fcntl(fd, fcntl.F_GETFL)
            print(f"  Status flags: {status:#x}")
            
            # Check if it's a DMA-BUF (typical for GPU memory)
            try:
                # Try to read from /proc to see what type of FD it is
                link = os.readlink(f"/proc/self/fd/{fd}")
                print(f"  FD type: {link}")
            except:
                pass
                
        except OSError as e:
            print(f"  ✗ Invalid FD: {e}")
    
    # Close FDs
    for fd in fds:
        try:
            os.close(fd)
        except:
            pass
    
    client.close()
    return len(fds) == 4

if __name__ == "__main__":
    # Start Vulkan app first
    print("Make sure Vulkan app is running with:")
    print("./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --offscreen 1 --renderer 0 --validation 0")
    print()
    
    success = test_fd_validity()
    print(f"\nTest: {'PASSED' if success else 'FAILED'}")