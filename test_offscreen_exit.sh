#!/bin/bash
# Test that offscreen mode exits properly when client disconnects

echo "Starting Vulkan app in offscreen mode..."
./_bin/Release/vk_lod_clusters --uds /tmp/vk_offscreen_test.sock --offscreen 1 --renderer 0 --validation 0 --gridcopies 1 2>&1 | tee /tmp/offscreen_test.log &
VK_PID=$!

echo "Vulkan PID: $VK_PID"

# Wait for socket AND for Vulkan to be ready to accept
echo "Waiting for socket..."
for i in {1..10}; do
    if [ -e /tmp/vk_offscreen_test.sock ]; then
        echo "Socket created"
        # Give Vulkan a bit more time to reach accept() call
        sleep 1
        break
    fi
    sleep 0.5
done

if [ ! -e /tmp/vk_offscreen_test.sock ]; then
    echo "ERROR: Socket not created"
    kill $VK_PID 2>/dev/null
    exit 1
fi

# Connect with Python
echo "Connecting Python client..."
python3 << 'EOF'
import socket, struct, json, array, os, time
print("Python: Connecting...")
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect('/tmp/vk_offscreen_test.sock')
size_data = client.recv(4)
json_size = struct.unpack('I', size_data)[0]
json_data = client.recv(json_size).decode()
print("Python: Connected, getting FDs...")
msg_data, ancdata, flags, addr = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
fds = array.array('i')
for cmsg_level, cmsg_type, cmsg_data in ancdata:
    if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
        fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
print(f"Python: Received {len(fds)} FDs")
for fd in fds: os.close(fd)
print("Python: Keeping connection open for 2 seconds...")
time.sleep(2)
print("Python: Closing connection...")
client.close()
print("Python: Disconnected")
EOF

echo "Waiting for Vulkan to exit..."
# Wait up to 5 seconds for process to exit
for i in {1..10}; do
    if ! ps -p $VK_PID > /dev/null 2>&1; then
        echo "✓ Vulkan process exited cleanly"
        rm -f /tmp/vk_offscreen_test.sock
        exit 0
    fi
    sleep 0.5
done

# If still running, that's a problem
if ps -p $VK_PID > /dev/null 2>&1; then
    echo "✗ ERROR: Vulkan process still running after client disconnect!"
    echo "Killing process..."
    kill $VK_PID
    sleep 1
    kill -9 $VK_PID 2>/dev/null
    exit 1
fi