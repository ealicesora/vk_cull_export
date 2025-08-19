#!/bin/bash
# Test UDS connection in GUI mode (non-offscreen)

echo "Starting Vulkan app in GUI mode with UDS..."
# Note: NOT using --offscreen flag
./_bin/Release/vk_lod_clusters --uds /tmp/vk_gui_test.sock --renderer 0 --validation 0 --gridcopies 1 2>&1 | tee /tmp/gui_mode.log &
VK_PID=$!

echo "Vulkan PID: $VK_PID (GUI mode)"

# Wait for socket
echo "Waiting for socket..."
for i in {1..20}; do
    if [ -e /tmp/vk_gui_test.sock ]; then
        echo "Socket created"
        sleep 1  # Give time for the thread to start accepting
        break
    fi
    sleep 0.5
done

if [ ! -e /tmp/vk_gui_test.sock ]; then
    echo "ERROR: Socket not created"
    kill $VK_PID 2>/dev/null
    exit 1
fi

# Connect with Python
echo "Connecting Python client to GUI mode app..."
python3 << 'EOF'
import socket, struct, json, array, os, time
print("Python: Connecting to GUI mode app...")
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect('/tmp/vk_gui_test.sock')
size_data = client.recv(4)
json_size = struct.unpack('I', size_data)[0]
json_data = client.recv(json_size).decode()
print("Python: Connected, getting FDs...")
msg_data, ancdata, flags, addr = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
fds = array.array('i')
for cmsg_level, cmsg_type, cmsg_data in ancdata:
    if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
        fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
print("=== PYTHON SIDE: Received FDs in GUI mode ===")
print(f"  Camera Memory FD:    {fds[0]}")
print(f"  Color Memory FD:     {fds[1]}")
print(f"  Camera Semaphore FD: {fds[2]}")
print(f"  Done Semaphore FD:   {fds[3]}")
print("==============================================")
for fd in fds: os.close(fd)
print("Python: Keeping connection for 2 seconds...")
time.sleep(2)
print("Python: Closing connection...")
client.close()
print("Python: Disconnected from GUI mode app")
EOF

echo ""
echo "GUI app should still be running after Python disconnects..."
sleep 2

# Check if process is still running
if ps -p $VK_PID > /dev/null 2>&1; then
    echo "✓ GUI mode app still running (as expected)"
    echo "Killing GUI app..."
    kill $VK_PID
    sleep 1
    kill -9 $VK_PID 2>/dev/null
else
    echo "✗ ERROR: GUI app exited (should keep running!)"
fi

# Check logs for FD output
echo ""
echo "Checking for FD logs from Vulkan side..."
grep "VULKAN SIDE" /tmp/gui_mode.log -A 6 || echo "No VULKAN SIDE logs found"

# Clean up
rm -f /tmp/vk_gui_test.sock /tmp/gui_mode.log