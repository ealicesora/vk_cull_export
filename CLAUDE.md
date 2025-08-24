# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build System

### Primary Build Commands

#### Recommended Build Process (Updated 2025-08-24)

**🎯 For Python Extension Development (BEST METHOD - VERIFIED 2025-08-24):**
```bash
# Step 1: Use sophisticated toolchain approach (separates conda Python from system C++)
# This method builds Python extensions successfully without GLIBC conflicts
# ✅ VERIFIED: Successfully builds 8.1MB extension with full LodClusters renderer

# IMPORTANT: Keep conda environment ACTIVE (needed for Python/pybind11)
conda activate vk2torch

# Clean previous build
rm -rf build-py

# Configure with toolchain file (uses system GCC-10, conda Python)
cmake -S . -B build-py \
  -DCMAKE_TOOLCHAIN_FILE=toolchains/system_no_conda.cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$HOME/anaconda3/envs/vk2torch/bin/python" \
  -DCMAKE_PREFIX_PATH="$HOME/VulkanSDK/1.4.321.1/x86_64" \
  -DUSE_DLSS=OFF \
  -DBUILD_PYTHON_EXT=ON

# Build (Python extension will be created)
# ✅ PIC issues have been resolved in CMakeLists.txt - no manual patches needed
cmake --build build-py --config Release -j4

# Result: build-py/_bin/Release/vk2torch_ext.cpython-310-x86_64-linux-gnu.so (8.1MB)
# VulkanSDK runtime libraries: build-py/_bin/Release/vulkan/
# Test: cd build-py/_bin/Release && python -c "import vk2torch_ext; print('✅ Success!')"

# ✅ VERIFIED BUILD OUTPUT:
# - Extension size: 8,133,568 bytes (contains full 3D renderer)
# - VulkanSDK libs: libvulkan.so.1, libshaderc_shared.so.1 (auto-packaged)
# - RPATH: $ORIGIN;$ORIGIN/vulkan (runtime library discovery)
# - Compatibility: Works with vk2torch conda environment
```

**🔧 Key Technical Solutions Applied:**
- **PIC Compilation**: Global `CMAKE_POSITION_INDEPENDENT_CODE ON` set before nvpro_core2 loading
- **GLIBC Isolation**: Toolchain file prevents conda sysroot contamination  
- **Unified Architecture**: `vklod_core_obj` OBJECT library eliminates code duplication
- **Runtime Packaging**: VulkanSDK libraries automatically copied with correct RPATH

**🎯 For Main Application (Vulkan App):**
```bash
# Option 1: Clean environment build (most reliable for main app)
./build_clean.sh

# Option 2: Conda-compatible build (if conda must be used)
./build_conda_fix.sh

# Option 3: Manual build with clean environment
# IMPORTANT: Deactivate conda environment if active to avoid GLIBC conflicts
conda deactivate

# Clean build directory if exists (optional for fresh build)
rm -rf build

# Configure build with GCC-10 and clean environment
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF

# Apply required patch to nvpro_core2 (only needed once after configure)
# Edit: build/_deps/nvpro_core2/nvutils/logger.cpp
# Around line 38-39, after #include <signal.h>, add:
#   #include <unistd.h>

# Build the project (use -j4 for parallel compilation)
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake --build build --config Release -j4

# Executable will be created at: _bin/Release/vk_lod_clusters
```

#### Quick Rebuild (after initial setup)
```bash
# For subsequent builds after code changes
conda deactivate  # If conda is active
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake --build build --config Release -j4
```

#### Alternative Build Commands (if above doesn't work)
```bash
# Configure build (creates build directory)
# Option 1: Use system default compiler (if GCC 10+ or Clang 12+)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Option 2: Specify GCC version explicitly (if you have multiple versions)
CC=gcc-12 CXX=g++-12 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
# or
CC=gcc-11 CXX=g++-11 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
# or  
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Build the project
cmake --build build --config Release

# For debug builds (includes more UI elements)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build --config Debug
```

### Build Requirements and Compatibility
- **Compiler**: GCC 10+ or Clang 12+ (C++20 support required)
  - ✅ GCC 12.x - Recommended (excellent C++20 support)
  - ✅ GCC 11.x - Good (full C++20 support) 
  - ✅ GCC 10.x - Minimum (basic C++20 support)
  - ❌ GCC 9.x - Not supported (incomplete C++20, missing std::span)

### Installing GCC 10+ on Ubuntu 20.04
If you only have GCC 9, you need to install a newer version:
```bash
# Add toolchain repository
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt update

# Install GCC-10 (minimum supported)
sudo apt install gcc-10 g++-10

# Or install GCC-11 (recommended)
sudo apt install gcc-11 g++-11

# Verify installation
gcc-10 --version
g++-10 --version
```
- **GPU**: NVIDIA GTX 1660 Ti or better (RTX series recommended for ray tracing)
- **RAM**: 8GB+ (16GB+ recommended for large scenes)
- **Storage**: ~2GB for build artifacts

### Toolchain System for Mixed Environments

**The Problem:** Building Python extensions in conda environments with VulkanSDK causes GLIBC version conflicts.

**The Solution:** Use CMake toolchain files to separate system C++ compilation from conda Python environments:

```bash
# Key files:
# toolchains/system_no_conda.cmake - Forces system compilers, ignores conda paths
# CMakeLists.txt - Supports pybind11 Python extension building
```

**Architecture:**
- **System compilers** (GCC-10): For C++ compilation, avoids conda GLIBC conflicts
- **Conda Python**: For pybind11 integration and Python module creation
- **Toolchain isolation**: Prevents conda cross-compilation toolchain contamination

**Result:** Python extensions build successfully while maintaining conda environment for testing.

### Common Build Issues and Solutions
1. **C++20 Compilation Errors**: Ensure using GCC 10+, try explicit compiler selection if needed
2. **Multiple compiler versions**: Use `CC=gcc-12 CXX=g++-12` to specify version
3. **Missing pthread symbols**: Already fixed in CMakeLists.txt with `Threads::Threads`
4. **Extension not available**: Ray tracing extensions are optional for non-RTX GPUs
5. **Out of memory during processing**: Use `--processingonly 1` and `--processingthreadpct 0.1`
6. **🆕 GLIBC conflicts in conda**: Use toolchain approach for Python extension development
7. **🆕 Python extension build failures**: Ensure using `conda activate vk2torch` + toolchain file

### Dependencies
- Requires Vulkan SDK 1.4.309.0 or later
- Uses CMake 3.22+ with C++20 standard
- Automatically downloads nvpro_core2 framework if not found
- Optionally downloads DLSS SDK when USE_DLSS=ON

### Key CMake Options
- `USE_DLSS=ON/OFF` - Enable DLSS denoising (default ON, recommend OFF for simpler builds)
- Build system automatically downloads Stanford Bunny glTF model as default scene

### Running the Application
```bash
# Basic execution (rasterization mode for compatibility)
./_bin/Release/vk_lod_clusters --renderer 0 --validation 0

# Memory-efficient single bunny mode
./_bin/Release/vk_lod_clusters --renderer 0 --validation 0 --gridcopies 1

# Ray tracing mode (requires RTX GPU)
./_bin/Release/vk_lod_clusters --renderer 1 --validation 0

# Process large scenes efficiently (two-step approach)
./_bin/Release/vk_lod_clusters --scene scene.gltf --processingonly 1 --processingthreadpct 0.1
./_bin/Release/vk_lod_clusters --scene scene.gltf --renderer 0 --validation 0
```

### Testing and Development Commands
```bash
# Check build success
ls -la _bin/Release/
file _bin/Release/vk_lod_clusters

# Get command line help
./_bin/Release/vk_lod_clusters --help

# Display system info (useful for debugging)
vulkaninfo | head -20
ldd _bin/Release/vk_lod_clusters
```

## Asset Resolution System (NEW - 2025-08-24)

### Unified Asset Resolution Architecture
The codebase implements a sophisticated asset resolution system to handle shader and model loading with absolute path requirements, particularly important for Python integration where working directory dependencies must be eliminated.

**Key Components:**
- **Asset Resolver** (`src/asset_resolver.hpp/cpp`): Unified path resolution for shaders and models
- **Search Path Management**: Configurable search paths for different asset types
- **Absolute Path Enforcement**: Critical for Python extension compatibility

### Asset Resolution API
```cpp
// Core asset resolution functions
std::filesystem::path resolve_shader(const std::filesystem::path& root, std::string_view rel);
std::filesystem::path resolve_model(const std::filesystem::path& root, std::string_view rel);

// Usage examples:
auto shader_path = assets::resolve_shader(m_assetRoot, "hbao_depthlinearize.comp.glsl");
auto model_path = assets::resolve_model(m_assetRoot, "house_new.glb");
```

### Shader Compilation Integration
**Critical Implementation Details:**
- **GlslCompiler Search Paths**: Must be configured BEFORE shader compilation
- **Initialization Order**: `Resources::setAssetRoot()` → configure search paths → `HbaoPass::setAssetRoot()` → reload shaders
- **Absolute Path Requirement**: shaderc requires absolute paths for reliable compilation
- **Include Resolution**: GLSL `#include` directives resolved via nvpro_core2's GlslIncluder

**Working Pattern in Resources::setAssetRoot():**
```cpp
// Step 1: Add search paths to GlslCompiler FIRST
std::vector<std::filesystem::path> shaderPaths = {
  assetRoot, assetRoot / "shaders", assetRoot / "resources"
};
m_glslCompiler.addSearchPaths(shaderPaths);

// Step 2: THEN trigger shader reload in dependent components
m_hbaoPass.setAssetRoot(assetRoot);
```

### Python Integration Benefits
- **Working Directory Independence**: Python can pass absolute asset_root without requiring specific CWD
- **Conda Environment Compatibility**: Works regardless of where Python process is launched
- **Error Prevention**: Eliminates "File not found" errors when shaders reference includes via relative paths

### Shader Loading Architecture
**HBAO Pass Integration:**
- Deferred shader compilation until `setAssetRoot()` called
- Uses GlslCompiler's default options (includes proper includer configuration)
- All 7 HBAO shaders compile successfully: depthlinearize, viewnormal, blur, blur_apply, calc, deinterleave, reinterleave

**NVHIZ Integration:**
- Dynamic shader loading via asset resolver for nvhiz-update.comp.glsl variants
- Supports multiple shader variants for different GPU capabilities

### Testing Asset Resolution
```python
# Python test pattern for asset resolution validation
import vk2torch_ext
import os

# Get absolute asset root (critical for reliable operation)  
root = os.path.abspath('path/to/assets')
print(f'[test] using asset_root = {root}')

# Extension handles absolute paths correctly
app = vk2torch_ext.Vk2TorchApp(512, 512, True, "house_new.glb", str(root))
```

### Common Asset Resolution Issues & Solutions
- **"File not found" shader errors**: Ensure asset resolver returns absolute paths, not relative
- **Include resolution failures**: Verify GlslCompiler search paths configured before shader compilation  
- **Python working directory issues**: Always pass absolute asset_root from Python
- **Initialization order problems**: Configure search paths before calling shader reload methods

## Architecture Overview

### Core Application Structure
- **Main Application**: `LodClusters` class in `src/lodclusters.hpp/cpp` - primary application element
- **Scene Management**: `Scene` class handles 3D model loading, cluster generation, and geometry processing
- **Rendering**: Dual rendering paths for rasterization (`RendererRasterClustersLod`) and ray tracing (`RendererRayTraceClustersLod`)
- **Resources**: `Resources` class manages Vulkan resources, buffers, and memory allocation
- **Context Bootstrap**: `core::BootstrapResult createVulkanContext()` in `src/core/context_bootstrap.*` - centralized Vulkan initialization
- **External Memory Integration**: `ExternalMemoryManager` in `src/external_memory.*` - handles Python/CUDA interop via FD export
- **PyBridge Element**: `ElementPyBridge` in `src/pybridge/element_pybridge.*` - nvapp::IAppElement for in-process Python integration

### Key Technologies
- **NVIDIA RTX Mega Geometry**: Implements continuous level of detail using mesh clusters
- **VK_NV_cluster_acceleration_structure**: For ray tracing with clusters (requires driver 572.16+)
- **VK_NV_mesh_shader**: For mesh shader-based rasterization
- **Streaming System**: On-demand geometry loading from RAM to VRAM

### Rendering Modes
1. **Rasterization Mode**: Uses mesh shaders to render clusters directly
2. **Ray Tracing Mode**: Builds BLAS/TLAS from clusters for ray tracing (default when supported)

### Scene Types
- **Preloaded Scene** (`scene_preloaded.cpp`): Loads all geometry upfront
- **Streaming Scene** (`scene_streaming.cpp`): Dynamic streaming system (default)

## Core Data Flow

### Scene Processing Pipeline
1. **Model Loading**: GLTF models processed via `Scene::loadGLTF()`
2. **Cluster Generation**: Uses nv_cluster_lod_builder library in `Scene::buildGeometryClusters()`
3. **LOD Hierarchy**: Creates continuous LOD structure in `Scene::processGeometry()`
4. **Cache System**: Saves processed data to `.nvsngeo` files for reuse

### Rendering Pipeline
1. **Traversal**: LOD hierarchy traversal in `shaders/traversal_*.comp.glsl`
2. **Culling**: Frustum and occlusion culling during traversal
3. **BLAS Building**: For ray tracing, builds bottom-level acceleration structures
4. **Rendering**: Either mesh shader rasterization or ray tracing

### Streaming System Operations
- **Request Processing**: Missing geometry groups identified during traversal
- **Memory Management**: GPU-driven CLAS allocator for ray tracing acceleration structures
- **Transfer Operations**: Asynchronous geometry uploads using transfer queue

## Shader Organization

### Shared Headers
- `shaders/shaderio.h` - Frame setup and debugging structures
- `shaders/shaderio_scene.h` - Scene and cluster geometry definitions
- `shaders/shaderio_building.h` - Traversal data structures
- `shaders/shaderio_streaming.h` - Streaming system structures

### Traversal Shaders
- `shaders/traversal_init.comp.glsl` - Initialize traversal nodes
- `shaders/traversal_run.comp.glsl` - Hierarchical LOD traversal kernel
- `shaders/build_setup.comp.glsl` - Preparation operations
- `shaders/blas_*.comp.glsl` - BLAS building for ray tracing

### Rendering Shaders
- `shaders/render_raster_clusters.mesh.glsl` - Mesh shader for rasterization
- `shaders/render_raytrace_clusters.rchit.glsl` - Ray tracing hit shader
- `shaders/stream_*.comp.glsl` - Streaming system operations

## Configuration and Command Line

### Key Configuration Structures
- `SceneConfig` - Cluster and LOD generation settings
- `RendererConfig` - Rendering pipeline configuration
- `StreamingConfig` - Memory and streaming parameters
- `FrameConfig` - Per-frame rendering state

### Important Command Line Options
- `--renderer 0` - Start with rasterization mode (use for non-RTX GPUs)
- `--renderer 1` - Ray tracing mode (requires RTX GPU and driver 572.16+)
- `--streaming 0` - Disable streaming (preload all geometry)
- `--gridcopies 1` - Single instance instead of grid (reduces memory usage)
- `--gridunique 0` - Reduce memory by true instancing
- `--clasallocator 0` - Use simple CLAS compaction instead of persistent allocator
- `--supersample 0` - Disable 2x super sampling
- `--validation 0` - Disable Vulkan validation for performance
- `--autoloadcache 0/1` - Control cache file loading
- `--autosavecache 0/1` - Control cache file saving
- `--mappedcache 1` - Use memory-mapped cache files (saves RAM)
- `--processingonly 1` - Process geometry and save cache, then exit
- `--processingthreadpct 0.1` - Use 10% of CPU threads (reduces memory usage during processing)
- `--uds <path>` - Enable Python integration via Unix Domain Socket at specified path
- `--offscreen 1` - Enable offscreen rendering for Python integration (no window display)

## Memory Management

### Cache System
- Processed geometry saved to `.nvsngeo` files next to original models
- Cache files can be large (GBs for complex scenes)
- Memory mapping option available via `--mappedcache 1`
- Cache invalidation requires manual deletion

### VRAM Management
- Persistent geometry: Lowest LOD always resident
- Dynamic geometry: Streamed based on camera distance and LOD requirements
- CLAS allocation: Two strategies - simple compaction or persistent GPU allocator

## Development Notes

### Processing Performance
- Multi-threaded geometry processing using configurable thread pools
- Processing time varies greatly (seconds to minutes for large scenes)
- Use `--processingonly 1` to reduce peak memory during processing

### Driver Requirements
- Cluster acceleration structure extension requires recent NVIDIA drivers (572.16+)
- Falls back to rasterization-only on older drivers
- Validation layers may produce expected warnings for new extensions

### Testing Scenes
- Default: Stanford Bunny (automatically downloaded)
- Additional scenes available: threedscans_animals, threedscans_statues
- Custom GLTF models supported via drag-and-drop or file dialog

## Troubleshooting

### Build Issues
- **"Extension not available" errors**: Ray tracing extensions are now optional, should fallback gracefully
- **pthread linking errors**: Fixed in current CMakeLists.txt 
- **C++20 compilation errors**: Ensure using GCC 10+ or Clang 12+. Try `CC=gcc-12 CXX=g++-12` if you have multiple versions
- **`isatty` not declared**: Need to add `#include <unistd.h>` to `build/_deps/nvpro_core2/nvutils/logger.cpp`
- **GLIBC version conflicts**: Anaconda environments can cause library conflicts. Try building outside conda environment or use `conda deactivate` first
- **Vulkan SDK linking errors**: If using custom Vulkan SDK causes GLIBC conflicts, try system Vulkan packages instead
- **Out of memory during build**: Use fewer parallel jobs: `cmake --build build -j4`
- **Compiler version conflicts**: Explicitly set compiler with `CC=gcc-12 CXX=g++-12 cmake ...`

### Build Scripts Available
- **`./build_clean.sh`**: Clean environment build with aggressive conda isolation
- **`./build_conda_fix.sh`**: Conda-compatible build using system libraries and static linking
- Both scripts automatically handle VulkanSDK detection and clean environment setup

### Known Build Patches Needed
1. **nvpro_core2 logger.cpp**: Add `#include <unistd.h>` after `#include <signal.h>` in the Unix section
   - Location: `build/_deps/nvpro_core2/nvutils/logger.cpp` around line 38-39
   - Error: `'isatty' was not declared in this scope`
   - Solution: Insert `#include <unistd.h>` after line with `#include <signal.h>`
2. **VMA ODR Violation Prevention**: 
   - **Status**: ✅ **FIXED** - VMA_IMPLEMENTATION centralized in `src/thirdparty/vma_impl.cpp`
   - All other files have VMA_IMPLEMENTATION removed to prevent duplicate symbols
3. **Conda/VulkanSDK GLIBC Conflicts**: 
   - **Symptoms**: `undefined reference to log2@GLIBC_2.29`, `__clock_getres@GLIBC_PRIVATE`
   - **Root Cause**: VulkanSDK libraries compiled against newer GLIBC than conda provides
   - **Solutions**: Use provided build scripts which handle environment isolation
   - **Manual Fix**: Use `conda deactivate` and clean PATH: `PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"`

### Runtime Issues
- **Crash on startup**: Use `--renderer 0 --validation 0` for maximum compatibility
- **Out of memory during processing**: Use `--processingonly 1 --processingthreadpct 0.1`
- **Poor performance**: Disable validation with `--validation 0`
- **Ray tracing not working**: Requires RTX GPU and driver 572.16+, fallback to `--renderer 0`
- **"Shader not found" at runtime**: Verify asset resolver configured properly, check absolute path resolution
- **HBAO effects not working**: Check if `VK2TORCH_DISABLE_HBAO` environment variable is set, ensure shaders compiled successfully

### Performance Optimization
- Use Release builds for performance testing
- Disable validation layers in production: `--validation 0`
- For large scenes, process once with `--processingonly 1`, then run normally
- Adjust grid copies for memory constraints: `--gridcopies 1`
- Use memory mapping for very large cached scenes: `--mappedcache 1`

## Python Integration (VK2Torch)

### Overview
The codebase includes a **production-ready** Python integration system that enables zero-copy access to rendered frames from Python/PyTorch via Unix Domain Sockets and CUDA external memory. This system provides real-time camera control and frame capture for AI/ML applications with strict CUDA v1 compliance.

### Architecture Components
- **ExternalMemoryManager** (`src/external_memory.*`): Manages Vulkan external memory resources, timeline semaphores, and UDS communication
  - **UDS Mode**: Traditional Unix Domain Socket communication with FD passing 
  - **In-Process Mode**: `initInProcess()` for direct pybind11 integration with `exportDepthBufferFdDup()` and `exportFrameDoneSemaphoreFdDup()`
- **PyBridge Element** (`src/pybridge/element_pybridge.*`): nvapp::IAppElement for in-process camera control and frame synchronization
- **pybind11 Extension** (`build-py/vk2torch_ext.cpython-*.so`): Built with toolchain approach, provides `VkLodBridge` class for direct Python integration
- **Python Clients**: 
  - `python/vk2torch_client.py`: Original working client with graceful fallbacks
  - `python/vk2torch_client_strict_fixed.py`: **PRODUCTION CLIENT** - Strict CUDA v1 compliant with mandatory dependencies
- **Frame Protocol**: Complete window-mode protocol with timeline semaphore synchronization

### Key Integration Points
- **FrameConfig**: Extended with `externalMemoryManager` pointer to enable per-frame external memory operations
- **Renderers**: Both raster and ray tracing renderers include image-to-buffer copy operations after rendering
- **Main Application**: Extended with `--uds` and `--offscreen` CLI parameters for Python integration mode
- **Synchronization Protocol**: `Python(camReady=N) → Vulkan(render→frameDone=N) → Python(tensor access)`

### Production Testing Commands
```bash
# Method 1: Complete integration test
# Terminal 1: Start Vulkan app (window mode recommended for stability)
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0 --gridcopies 1

# Terminal 2: Run strict client test
conda activate vk2torch
python -c "
import vk2torch_client_strict_fixed
import numpy as np

with vk2torch_client_strict_fixed.VK2TorchClientStrictFixed('/tmp/vk2torch.sock') as client:
    if client.connect():
        print(f'✅ Connected: {client.width}x{client.height}')
        print(f'✅ CUDA support: {client.has_strict_cuda_support}')
        
        view = np.eye(4, dtype=np.float32)
        proj = np.eye(4, dtype=np.float32)
        client.update_camera(view, proj)
        frame = client.get_frame()
        print(f'✅ Frame: {frame.shape} on {frame.device}')
        client.save_frame_png(frame, 'test.png')
        print('🎉 COMPLETE SUCCESS!')
"

# Method 2: Automated test script (in python/ directory)
cd python && python test_final_success.py

# Method 3: Quick shell-based test
./test_vk2torch.sh

# Method 4: Multiple frame test with window mode
# Terminal 1: Start with window mode (more stable than offscreen)
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --renderer 0 --validation 0 --gridcopies 1

# Terminal 2: Test multiple frames
cd python && python -c "
import vk2torch_client
client = vk2torch_client.VK2TorchClient('/tmp/vk2torch.sock')
if client.connect():
    print('Connected successfully')
    for i in range(3):
        frame = client.get_frame(timeout_ms=2000)
        print(f'Frame {i+1}: {frame.shape if frame is not None else \"timeout\"}')"
```

### Python Extension Building (NEW - Toolchain Method)
```bash
# BEST METHOD: Use toolchain approach for reliable Python extension building
# This method successfully separates conda Python from system C++ compilation

# Keep conda environment active (needed for pybind11)
conda activate vk2torch

# Build Python extension with toolchain isolation
rm -rf build-py
cmake -S . -B build-py \
  -DCMAKE_TOOLCHAIN_FILE=toolchains/system_no_conda.cmake \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$HOME/anaconda3/envs/vk2torch/bin/python" \
  -DCMAKE_PREFIX_PATH="$HOME/VulkanSDK/1.4.321.1/x86_64" \
  -DUSE_DLSS=OFF \
  -DBUILD_PYTHON_EXT=ON

# Apply nvpro_core2 logger patch (add #include <unistd.h> after #include <signal.h>)
# Then build:
cmake --build build-py --config Release -j4

# Test the extension
cd build-py && python -c "import vk2torch_ext; print('✅ Success! Available:', dir(vk2torch_ext))"
```

### Python Environment Setup
```bash
# MANDATORY: Use the pre-configured vk2torch environment
conda activate vk2torch

# Verify CUDA functionality (required for strict client)
python -c "import cupy, torch; print('✅ CUDA ready')"

# Environment includes: CuPy, PyTorch, CUDA driver libraries
# CRITICAL: Do not modify CUDA ctypes struct definitions - they are CUDA v1 compliant
```

### Production Client Usage (Recommended)
```python
from vk2torch_client_strict_fixed import VK2TorchClientStrictFixed, create_camera_matrices
import numpy as np

# Strict client - raises exceptions on any failure (production ready)
with VK2TorchClientStrictFixed('/tmp/vk2torch.sock') as client:
    client.connect()  # Raises RuntimeError on failure
    
    # Test semaphore ping-pong (validates synchronization)
    client.test_semaphore_ping_pong(3)
    
    # Camera control with orbit movement
    for i in range(5):
        distance = 4.0 + i * 0.5
        yaw = i * 0.3
        view_matrix, proj_matrix = create_camera_matrices(distance, yaw, 0.0)
        
        client.update_camera(view_matrix, proj_matrix)  # Signals camReady=N
        frame = client.get_frame(timeout_ms=2000)       # Waits frameDone=N
        
        print(f"Frame {i}: {frame.shape} {frame.dtype} on {frame.device}")
        client.save_frame_png(frame, f"frame_{i:03d}.png")
```

### Integration Architecture Details
The Python integration implements a **zero-copy GPU-to-GPU pipeline**:

1. **External Memory Export**: Vulkan creates exportable device-local buffers using `VK_KHR_external_memory_fd` with dedicated allocation
2. **Timeline Semaphore Sync**: Uses `VK_KHR_timeline_semaphore` for frame-accurate synchronization between Vulkan and CUDA contexts
3. **Unix Domain Sockets**: File descriptor passing via SCM_RIGHTS for secure inter-process resource sharing
4. **GPU UUID Matching**: Ensures Vulkan and CUDA use the same physical GPU in multi-GPU systems
5. **CUDA v1 Compliance**: All structures exactly match CUDA Driver API v1 specifications with proper reserved fields

### Client Comparison
| Feature | `vk2torch_client.py` | `vk2torch_client_strict_fixed.py` |
|---------|---------------------|-----------------------------------|
| **Error Handling** | Graceful fallbacks | Exceptions (strict) |
| **CUDA Requirements** | Optional | Mandatory |
| **Production Ready** | Development/Testing | ✅ **Production** |
| **Compliance** | Best effort | Strict CUDA v1 |

### Performance Expectations
- **Semaphore roundtrip latency**: 3-5ms
- **Frame capture time**: 1-50ms (scene dependent)
- **Zero-copy tensor access**: <1ms (direct GPU memory)
- **Memory usage**: ~8MB for 1920x1080 RGBA

### Known Limitations & Solutions
- **CUDA external memory import may fail**: Driver compatibility issue, but system continues to work
- **Timeline semaphore compatibility**: Requires recent NVIDIA drivers (>=572.16 recommended)
- **Environment dependency**: Must use `conda activate vk2torch` for CUDA functionality
- **Linux only**: Uses Unix domain sockets - no Windows support currently

### Troubleshooting Python Integration
- **"Connection refused"**: Ensure Vulkan app started with `--uds <path>` (prefer window mode over `--offscreen 1`)
- **"CUDA import failed"**: Check driver version and run `conda activate vk2torch`
- **"File descriptor errors"**: Verify socket path is accessible and not in use
- **"Semaphore timeout"**: Increase timeout or check GPU load - window mode is more stable than offscreen
- **"Import error"**: Run `python -c "import cupy, torch"` to verify environment
- **"Vulkan hangs after 2-3 frames"**: Known issue with timeline semaphore signaling, use window mode instead of offscreen
- **"Device lost errors"**: Indicates duplicate timeline semaphore signaling - fixed in current implementation
- **"NVIDIA Xid 39 errors"**: GPU errors from invalid commands - ensure not running old versions with duplicate signaling bug
- **"Shader not found" errors**: Verify asset resolver returning absolute paths and GlslCompiler search paths configured
- **"HBAO compilation failed"**: Check that `setAssetRoot()` called before shader compilation, verify hbao.h include resolution

## Development Workflow

### Code Organization Patterns
- **Renderer Architecture**: Two main renderer implementations (`RendererRasterClustersLod` and `RendererRayTraceClustersLod`) share common base class and scene management
- **Shader-Host Communication**: Data structures in `shaders/shaderio_*.h` define shared interfaces between host C++ and device GLSL code
- **Scene Polymorphism**: `Scene` base class with `ScenePreloaded` and `SceneStreaming` implementations for different memory management strategies
- **External Integration**: `ExternalMemoryManager` can be optionally integrated via `FrameConfig::externalMemoryManager` pointer
- **Bootstrap Pattern**: Vulkan context creation centralized in `core::createVulkanContext()` to avoid code duplication
- **Element Architecture**: All UI and integration components inherit from `nvapp::IAppElement` (onAttach/onDetach/onRender lifecycle)
- **Memory Management**: VMA (Vulkan Memory Allocator) implementation centralized in `src/thirdparty/vma_impl.cpp` to prevent ODR violations
- **Asset Resolution Pattern**: Unified asset resolver (`src/asset_resolver.hpp/cpp`) eliminates working directory dependencies
- **Directory Structure**: 
  - `src/core/`: Core infrastructure (bootstrap, context management)
  - `src/pybridge/`: Python integration elements and bridges
  - `src/pybind/`: pybind11 extension module implementation
  - `src/thirdparty/`: Third-party library implementations (VMA, etc.)
  - `shaders/`: GLSL shaders with shared headers for host-device communication

### Testing Strategy
- **Unit Tests**: Individual component tests in `python/test_*.py` for isolated functionality
- **Integration Tests**: End-to-end pipeline tests combining Vulkan rendering with Python clients
- **Performance Tests**: Use `--processingonly 1` mode for geometry processing benchmarks
- **Compatibility Tests**: Multiple renderer modes (`--renderer 0/1`) and streaming configurations (`--streaming 0/1`)

### Debugging Tools
```bash
# Enable Vulkan validation for development
./_bin/Release/vk_lod_clusters --validation 1

# Debug external memory integration
./_bin/Release/vk_lod_clusters --uds /tmp/debug.sock --offscreen 1 --validation 1

# Monitor GPU memory usage during streaming
vulkaninfo --summary && ./_bin/Release/vk_lod_clusters --streaming 1 --gridcopies 1

# Check Python client connectivity without CUDA dependencies
python python/test_optimizations.py /tmp/debug.sock

# Test asset resolution system
python debug_vk2torch.py  # Uses absolute asset_root path
```

### Important Implementation Notes
- **Thread Safety**: `ExternalMemoryManager` uses background echo thread for semaphore testing - ensure proper synchronization in deinit
- **Memory Alignment**: Camera buffers must be 4KB aligned for CUDA compatibility - this is handled automatically
- **GPU UUID Validation**: Multi-GPU systems require UUID matching between Vulkan and CUDA contexts for zero-copy functionality
- **File Descriptor Management**: Unix domain sockets use SCM_RIGHTS for FD passing - ensure proper cleanup to avoid leaks
- **Socket Communication**: The system minimizes per-frame socket overhead by using shared memory for camera data and GPU timeline semaphores for synchronization. Only fallback to socket communication if shared memory fails.
- **Asset Resolution Timing**: GlslCompiler search paths must be configured before any shader compilation - failing to do this causes "File not found" errors
- **Absolute Path Requirement**: Python integration requires absolute asset_root paths for reliable operation across different working directories
- **Shader Compilation Order**: HBAO and NVHIZ shaders are compiled on-demand when setAssetRoot() is called, not during init()

### Extension Points
- **Custom Renderers**: Inherit from base `Renderer` class and integrate with `LodClusters::createRenderer()`
- **Scene Sources**: Implement `Scene` interface for custom geometry sources (current: preloaded vs streaming)
- **Python Clients**: Extend `VK2TorchClientStrictFixed` for application-specific camera control or tensor processing
- **Memory Allocators**: Replace streaming allocator implementations in `stream_allocator_*.comp.glsl` and `stream_compaction_*.comp.glsl`

### VK2Torch Development Notes
- **Client Implementation**: Use `vk2torch_client_strict_fixed.py` as the reference implementation - it's based on the proven working client with strict validation added
- **CUDA Structure Compliance**: Do not modify the CUDA ctypes structure definitions - they are carefully crafted to match CUDA Driver API v1 specifications
- **Environment Requirement**: Always use `conda activate vk2torch` - this environment contains the required CuPy, PyTorch, and CUDA libraries
- **Testing Strategy**: The comprehensive test suite in `test_final_success.py` validates the complete pipeline including semaphore synchronization, camera control, and zero-copy tensor access

### Critical Timeline Semaphore Implementation (src/lodclusters.cpp:740)
The timeline semaphore synchronization includes a critical fix to prevent GPU crashes:
```cpp
static uint64_t lastSignaledFrameNumber = 0;
if(m_currentExternalFrameNumber > lastSignaledFrameNumber) {
    // Safe to signal - prevents duplicate signaling that causes Xid 39 errors
    lastSignaledFrameNumber = m_currentExternalFrameNumber;
    m_app->addSignalSemaphore(frameDoneSubmit);
}
```
**NEVER modify this duplicate signaling prevention** - it's essential for GPU stability.
- remember to change constexpr int32_t numFramesInFlight = 1; in application.cpp, when re-pull the nvpro_core2 repo
- ignore the offscreen mode in vk_cluser, use headless mode instead.

### Socket Communication Architecture
The VK2Torch integration implements a minimal-socket design:
- **Handshake Phase**: One-time exchange of configuration JSON + file descriptors via Unix Domain Socket with SCM_RIGHTS
- **Runtime Phase**: Zero socket messages per frame in normal operation
  - Camera data transferred via POSIX shared memory (`/vk2torch_camera`) with seqlock protocol
  - Frame synchronization via GPU timeline semaphores (imported during handshake)
  - Socket used only as fallback if shared memory unavailable (sends binary "CAM1" format or JSON)
- This achieves near-zero CPU overhead for inter-process communication
- never make a "simplified version without LodClusters dependency"