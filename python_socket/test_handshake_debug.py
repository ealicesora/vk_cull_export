#!/usr/bin/env python3
"""Debug handshake completion issue."""

import sys
import socket
import struct
import json

def test_handshake():
    """Test basic handshake with Vulkan."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    
    try:
        sock.connect('/tmp/vk2torch.sock')
        print("✅ Connected to socket")
        
        # Read handshake size
        size_data = sock.recv(4)
        if len(size_data) != 4:
            print(f"❌ Failed to read size, got {len(size_data)} bytes")
            return False
        
        json_size = struct.unpack('I', size_data)[0]
        print(f"📦 Expecting JSON of size {json_size}")
        
        # Read JSON data
        json_data = b''
        while len(json_data) < json_size:
            chunk = sock.recv(json_size - len(json_data))
            if not chunk:
                print("❌ Connection closed while reading JSON")
                return False
            json_data += chunk
        
        handshake = json.loads(json_data.decode('utf-8'))
        print(f"📋 Handshake data: {json.dumps(handshake, indent=2)}")
        
        # Read file descriptors
        import array
        fds = array.array('i')
        msg, ancdata, flags, addr = sock.recvmsg(1, socket.CMSG_LEN(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data)
                print(f"📁 Received {len(fds)} file descriptors: {list(fds)}")
        
        # Send handshake completion
        completion_msg = b"HANDSHAKE_COMPLETE"
        sock.send(completion_msg)
        print(f"✅ Sent completion message: {completion_msg}")
        
        # Try to read response
        sock.settimeout(1.0)
        try:
            response = sock.recv(1024)
            if response:
                print(f"📨 Got response: {response}")
        except socket.timeout:
            print("⏱️ No response after completion (timeout)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        sock.close()

if __name__ == "__main__":
    # Start Vulkan first
    import subprocess
    import time
    
    print("Starting Vulkan app...")
    proc = subprocess.Popen([
        './_bin/Release/vk_lod_clusters',
        '--uds', '/tmp/vk2torch.sock',
        '--renderer', '0',
        '--validation', '0', 
        '--gridcopies', '1'
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    # Wait for it to start
    time.sleep(8)
    
    print("\nTesting handshake...")
    success = test_handshake()
    
    # Kill Vulkan
    proc.terminate()
    proc.wait()
    
    sys.exit(0 if success else 1)