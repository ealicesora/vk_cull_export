#!/bin/bash

echo "Starting VK2Torch Integration Test"
echo "=================================="

# Kill any existing processes
pkill -f vk_lod_clusters 2>/dev/null
sleep 1

# Start Vulkan in background
echo "Starting Vulkan application..."
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0 --gridcopies 1 2>&1 | grep -E "Frame|ERROR|Python|Signaling" &
VULKAN_PID=$!

# Wait for initialization
echo "Waiting for Vulkan to initialize..."
sleep 12

# Check if Vulkan is still running
if ! ps -p $VULKAN_PID > /dev/null; then
    echo "ERROR: Vulkan crashed during initialization"
    exit 1
fi

echo "Vulkan is running, starting Python test..."

# Run Python test
cd python
timeout 10 python -c "
import sys
sys.path.insert(0, '.')
import vk2torch_client
import numpy as np

print('Connecting to Vulkan...')
client = vk2torch_client.VK2TorchClient('/tmp/vk2torch.sock')
if not client.connect():
    print('Failed to connect')
    sys.exit(1)

print(f'Connected: {client.width}x{client.height}')
print(f'CUDA: {client.has_cuda_support}')

# Just wait for frame 1
print('\\nWaiting for frame 1...')
client.frame_number = 1
try:
    frame = client.get_frame(timeout_ms=3000)
    if frame is not None:
        print(f'Got frame 1: {frame.shape}')
    else:
        print('Frame 1 timeout')
except Exception as e:
    print(f'Error: {e}')

client.disconnect()
print('Disconnected')
"

# Kill Vulkan
echo "Cleaning up..."
kill $VULKAN_PID 2>/dev/null

echo "Test complete"