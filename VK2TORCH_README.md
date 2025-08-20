# VK2Torch: Vulkan to PyTorch Zero-Copy GPU Integration

This system provides zero-copy GPU-to-GPU frame capture and camera control between Vulkan rendering and Python/PyTorch via CUDA external memory and timeline semaphores.

## Architecture Overview

The VK2Torch system implements a complete window-mode frame protocol:

1. **Python Side**: Writes camera parameters to GPU buffer → signals `camReady=N` 
2. **Vulkan Side**: Waits for `camReady=N` → renders frame → copies to color buffer → signals `frameDone=N`
3. **Python Side**: Waits for `frameDone=N` → accesses frame as zero-copy PyTorch tensor

### Key Features

- **Zero-Copy Access**: Direct GPU memory sharing via VK_KHR_external_memory_fd
- **Timeline Synchronization**: Frame-accurate sync via VK_KHR_timeline_semaphore
- **CUDA Compliance**: Strict adherence to CUDA Driver API v1 specifications
- **Dedicated Allocation**: All external memory uses dedicated allocation for maximum compatibility
- **Window Mode**: Renders to window while simultaneously capturing frames

## Quick Start

### Prerequisites

```bash
# 1. Ensure you have NVIDIA GPU with recent drivers (>=572.16 recommended)
# 2. Vulkan SDK 1.4.309.0+
# 3. CUDA 11.0+ with driver support
# 4. Python environment with CuPy and PyTorch
```

### Build Vulkan Application

```bash
# Navigate to project directory
cd vk_lod_clusters

# Build with GCC-10 (clean environment recommended)
conda deactivate  # If conda is active
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF

PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake --build build --config Release -j4
```

### Setup Python Environment

```bash
# Activate the vk2torch environment (should include CuPy, PyTorch, etc.)
conda activate vk2torch

# Verify CUDA functionality
python -c "import cupy as cp; print('CuPy version:', cp.__version__)"
python -c "import torch; print('PyTorch CUDA:', torch.cuda.is_available())"
```

## Usage Examples

### Basic Window Mode Test

```bash
# Terminal 1: Start Vulkan application
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0 --gridcopies 1

# Terminal 2: Run Python client
conda activate vk2torch
python python/test_window_mode_protocol.py
```

### Comprehensive System Validation

```bash
# Terminal 1: Start Vulkan app for testing
./_bin/Release/vk_lod_clusters --uds /tmp/test_complete.sock --renderer 0 --validation 0 --gridcopies 1

# Terminal 2: Run full validation suite
conda activate vk2torch
python python/test_complete_system.py
```

### Custom Integration Example

```python
from python.vk2torch_client_strict import VK2TorchClientStrict, create_camera_matrices

with VK2TorchClientStrict("/tmp/vk2torch.sock") as client:
    if client.connect():
        # Control camera
        view_matrix, proj_matrix = create_camera_matrices(distance=5.0, yaw=1.0, pitch=0.2)
        client.update_camera(view_matrix, proj_matrix)
        
        # Get zero-copy frame
        tensor = client.get_frame(timeout_ms=2000)
        if tensor is not None:
            print(f"Frame: {tensor.shape} {tensor.dtype} on {tensor.device}")
            
            # Save or process tensor
            client.save_frame_png(tensor, "frame.png")
```

## Command Line Options

### Vulkan Application

- `--uds <path>`: Unix domain socket path (default: `/tmp/vk2torch.sock`)
- `--offscreen 1`: Enable offscreen rendering (no window display)
- `--renderer 0`: Use rasterization renderer (most compatible)
- `--renderer 1`: Use ray tracing renderer (requires RTX GPU)
- `--validation 0`: Disable Vulkan validation (better performance)
- `--gridcopies 1`: Single model instance (reduces memory usage)

### Environment Variables

- `VK2TORCH_TEST_SEMAPHORE=1`: Enable semaphore echo testing mode

## Technical Details

### Memory Management

- **Camera Buffer**: Contains FrameConstants structure (matrices, viewport, etc.)
- **Color Buffer**: RGBA8 format with tight row packing (row_pitch = width * 4)
- **Allocation**: All buffers use `CUDA_EXTERNAL_MEMORY_DEDICATED` flag
- **Size Handling**: CUDA import uses Vulkan `allocationSize`, buffer access uses logical size

### Synchronization Protocol

```
Frame N Timeline:
1. Python: Write camera params → Signal camReady=N
2. Vulkan: Wait camReady=N → Render → Copy image → Signal frameDone=N  
3. Python: Wait frameDone=N → Access tensor → Ready for Frame N+1
```

### CUDA Structures (Strict v1 Compliance)

All CUDA structures exactly match cuda.h v1 specifications:

```c
// External memory handle
CUDA_EXTERNAL_MEMORY_HANDLE_DESC {
    .type = CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD,
    .handle.fd = vulkan_fd,
    .size = vulkan_allocation_size,  // NOT logical buffer size
    .flags = CUDA_EXTERNAL_MEMORY_DEDICATED,
    .reserved[16] = {0}  // Mandatory reserved field
}

// Buffer descriptor for access
CUDA_EXTERNAL_MEMORY_BUFFER_DESC {
    .offset = 0,
    .size = logical_buffer_size,  // For actual usage
    .flags = 0,
    .reserved[16] = {0}  // Mandatory reserved field
}
```

## Testing and Validation

The system includes comprehensive tests:

1. **Semaphore Ping-Pong**: 42-iteration roundtrip latency test
2. **Camera Buffer**: Write/verify pattern test
3. **Color Buffer Layout**: Checkerboard validation with proper stride handling
4. **End-to-End**: 100 frame test with animated camera movement
5. **Stability**: 500 frame endurance test with memory monitoring

### Expected Performance

- Semaphore roundtrip: 1-5ms typical
- Frame capture: 10-50ms depending on scene complexity
- Zero-copy tensor access: <1ms (no host memory transfers)

## Troubleshooting

### Common Issues

**Connection Refused**
```bash
# Ensure Vulkan app is running with --uds parameter
ps aux | grep vk_lod_clusters
```

**CUDA Import Error 1**
```
# Driver compatibility issue - try different buffer sizes
# Error is logged but basic connectivity will still work
```

**Memory Growth**
```bash
# Monitor with system validator
python python/test_complete_system.py
```

**Build Issues**
```bash
# Use clean environment without conda
conda deactivate
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" CC=gcc-10 CXX=g++-10 cmake --build build --config Release
```

### Debug Information

Enable detailed logging:
```bash
# Vulkan side
./_bin/Release/vk_lod_clusters --validation 1 --uds /tmp/debug.sock

# Python side - check logs
tail -f vk2torch_test.log
```

## Limitations

- **Linux Only**: Uses Unix domain sockets and Linux-specific external memory
- **NVIDIA GPUs**: Requires CUDA-capable GPU with external memory support
- **Driver Version**: Timeline semaphore support requires recent drivers
- **Memory Overhead**: Dedicated allocation may use more VRAM than necessary

## Future Improvements

- Windows support via named pipes or shared memory
- Multi-GPU support with explicit device selection  
- Asynchronous camera updates with double buffering
- Compression support for bandwidth optimization
- Direct integration with popular ML frameworks

## Contributing

When modifying the system:

1. **Maintain Strict CUDA Compliance**: Do not modify ctypes structure definitions
2. **Test All Validation Cases**: Run complete system validation before commits
3. **Document Breaking Changes**: Update this README for API changes
4. **Memory Safety**: Verify no FD leaks with extended testing

## License

This project follows the same license terms as the parent vk_lod_clusters project.