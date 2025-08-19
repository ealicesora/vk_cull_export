#!/usr/bin/env python3
"""Simple test to show FD values from both sides"""

import subprocess
import time
import socket
import struct
import json
import array
import os

def start_vulkan_app():
    """Start Vulkan app and wait for it to be ready"""
    print("Starting Vulkan app...")
    proc = subprocess.Popen([
        "./_bin/Release/vk_lod_clusters",
        "--uds", "/tmp/vk2torch_simple.sock",
        "--offscreen", "1",
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    # Wait for socket to be created
    for _ in range(10):
        if os.path.exists("/tmp/vk2torch_simple.sock"):
            print("Vulkan app ready!")
            return proc
        time.sleep(0.5)
    
    print("Vulkan app failed to create socket")
    proc.kill()
    return None

def connect_and_get_fds():
    """Connect to Vulkan app and get FDs"""
    print("\nConnecting to Vulkan app...")
    
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect("/tmp/vk2torch_simple.sock")
    
    # Read handshake
    size_data = client.recv(4)
    json_size = struct.unpack('I', size_data)[0]
    json_data = client.recv(json_size).decode()
    handshake = json.loads(json_data)
    print(f"Handshake: {handshake['w']}x{handshake['h']}")
    
    # Receive FDs
    msg_data, ancdata, flags, addr = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
    
    fds = array.array("i")
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
            fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
    
    print("\n=== PYTHON SIDE: Received FDs ===")
    print(f"  Camera Memory FD:    {fds[0]}")
    print(f"  Color Memory FD:     {fds[1]}")
    print(f"  Camera Semaphore FD: {fds[2]}")
    print(f"  Done Semaphore FD:   {fds[3]}")
    print("==================================")
    
    # Close FDs
    for fd in fds:
        os.close(fd)
    
    client.close()

def main():
    # Start Vulkan app
    proc = start_vulkan_app()
    if not proc:
        return
    
    # Wait a bit for initialization
    time.sleep(2)
    
    # Connect and get FDs
    connect_and_get_fds()
    
    # Get Vulkan output to see its FD logs
    print("\n=== VULKAN SIDE OUTPUT ===")
    proc.terminate()
    output, _ = proc.communicate(timeout=2)
    
    # Find the FD logging in output
    for line in output.split('\n'):
        if 'VULKAN SIDE' in line or 'FD:' in line or 'Memory FD' in line or 'Semaphore FD' in line:
            print(line)
    
    print("\n=== COMPARISON COMPLETE ===")

if __name__ == "__main__":
    main()