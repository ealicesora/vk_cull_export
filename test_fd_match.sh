#!/bin/bash
# Script to test FD matching between Vulkan and Python

echo "Starting Vulkan app..."
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch_compare.sock --offscreen 1 --renderer 0 --validation 0 --gridcopies 1 > /tmp/vulkan_fd.log 2>&1 &
VK_PID=$!

# Wait for socket
echo "Waiting for socket..."
for i in {1..10}; do
    if [ -e /tmp/vk2torch_compare.sock ]; then
        break
    fi
    sleep 0.5
done

# Connect with Python
echo "Connecting with Python..."
python3 << 'EOF'
import socket, struct, json, array, os
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect('/tmp/vk2torch_compare.sock')
size_data = client.recv(4)
json_size = struct.unpack('I', size_data)[0]
json_data = client.recv(json_size).decode()
msg_data, ancdata, flags, addr = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
fds = array.array('i')
for cmsg_level, cmsg_type, cmsg_data in ancdata:
    if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
        fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
print('=== PYTHON SIDE: Received FDs ===')
print(f'  Camera Memory FD:    {fds[0]}')
print(f'  Color Memory FD:     {fds[1]}')
print(f'  Camera Semaphore FD: {fds[2]}')
print(f'  Done Semaphore FD:   {fds[3]}')
print('==================================')
for fd in fds: os.close(fd)
client.close()
EOF

# Wait a bit then kill Vulkan
sleep 1
kill $VK_PID 2>/dev/null

# Check Vulkan output
echo ""
echo "Checking Vulkan output for FD logs..."
grep "VULKAN SIDE" /tmp/vulkan_fd.log -A 6 || echo "No VULKAN SIDE logs found"
grep "Camera Memory FD" /tmp/vulkan_fd.log || echo "No FD logs found in Vulkan output"

# Clean up
rm -f /tmp/vk2torch_compare.sock /tmp/vulkan_fd.log