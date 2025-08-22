#!/usr/bin/env python3
"""Simple handshake test that checks Vulkan logs."""

import subprocess
import time
import socket
import struct
import json
import array

def test_handshake_with_logs():
    """Test handshake and capture Vulkan output."""
    
    print("Starting Vulkan app with logging...")
    proc = subprocess.Popen([
        './_bin/Release/vk_lod_clusters',
        '--uds', '/tmp/vk2torch.sock',
        '--renderer', '0',
        '--validation', '0', 
        '--gridcopies', '1'
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    # Wait for startup
    time.sleep(8)
    
    print("\nConnecting to socket...")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    
    try:
        sock.connect('/tmp/vk2torch.sock')
        print("✅ Connected")
        
        # Read handshake
        size_data = sock.recv(4)
        json_size = struct.unpack('I', size_data)[0]
        print(f"📦 Expecting JSON of size {json_size}")
        
        json_data = sock.recv(json_size)
        handshake = json.loads(json_data.decode('utf-8'))
        print(f"✅ Got handshake data")
        
        # Read FDs
        fds = array.array('i')
        msg, ancdata, flags, addr = sock.recvmsg(1, socket.CMSG_LEN(4 * 4))
        
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data)
                print(f"✅ Received {len(fds)} FDs")
        
        # Don't send anything - just wait a bit
        print("⏳ Waiting 2 seconds...")
        time.sleep(2)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        sock.close()
    
    # Kill and get output
    proc.kill()  # Use kill instead of terminate
    try:
        output, _ = proc.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        output = ""
    
    print("\n=== VULKAN OUTPUT ===")
    # Look for relevant log lines
    for line in output.split('\n'):
        if any(x in line for x in ['About to send', 'Sending', 'Successfully', 'Failed', 'Handshake', 'ERROR', 'Python']):
            print(line)
    
    return True

if __name__ == "__main__":
    test_handshake_with_logs()