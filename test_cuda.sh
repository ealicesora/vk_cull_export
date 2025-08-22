#!/bin/bash

echo "Starting VK2Torch CUDA Test"
echo "============================"

# Kill any existing processes
pkill -f vk_lod_clusters 2>/dev/null
sleep 1

# Start Vulkan 
echo "Starting Vulkan application..."
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0 --gridcopies 1 2>&1 > vulkan_output.log &
VULKAN_PID=$!

# Wait for initialization
echo "Waiting for Vulkan to initialize..."
sleep 12

# Check if Vulkan is still running
if ! ps -p $VULKAN_PID > /dev/null; then
    echo "ERROR: Vulkan crashed during initialization"
    cat vulkan_output.log | tail -20
    exit 1
fi

echo "Vulkan is running (PID: $VULKAN_PID)"

# Run Python test with conda
echo "Running Python test with CUDA..."
conda run -n vk2torch python python/test_minimal.py

echo ""
echo "Checking Vulkan log for frames..."
grep -E "Frame.*External|Frame.*Signaling|ERROR" vulkan_output.log | tail -20

# Kill Vulkan
echo ""
echo "Cleaning up..."
kill $VULKAN_PID 2>/dev/null
wait $VULKAN_PID 2>/dev/null

echo "Test complete"