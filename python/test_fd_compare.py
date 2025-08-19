#!/usr/bin/env python3
"""Compare FDs from Vulkan and Python sides"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from vk2torch_client import VK2TorchClient

def main():
    print("Connecting to Vulkan app...")
    client = VK2TorchClient(socket_path="/tmp/vk2torch.sock")
    
    if client.connect():
        print("Connected successfully!")
        print("Check the logs above to compare FDs from both sides")
        client.disconnect()
    else:
        print("Connection failed")

if __name__ == "__main__":
    main()