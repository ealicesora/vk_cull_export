# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build System

### Primary Build Commands

#### Successful Build Process (Tested 2025-08-19)
```bash
# IMPORTANT: Deactivate conda environment if active to avoid GLIBC conflicts
conda deactivate

# Clean build directory if exists
rm -rf build && mkdir build

# Configure build with GCC-10 and clean environment
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF

# Apply required patch to nvpro_core2 (this will be needed each build)
# Add #include <unistd.h> after #include <signal.h> in:
# build/_deps/nvpro_core2/nvutils/logger.cpp

# Build the project
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
CC=gcc-10 CXX=g++-10 cmake --build build --config Release

# Executable will be created at: _bin/Release/vk_lod_clusters
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

### Common Build Issues and Solutions
1. **C++20 Compilation Errors**: Ensure using GCC 10+, try explicit compiler selection if needed
2. **Multiple compiler versions**: Use `CC=gcc-12 CXX=g++-12` to specify version
3. **Missing pthread symbols**: Already fixed in CMakeLists.txt with `Threads::Threads`
4. **Extension not available**: Ray tracing extensions are optional for non-RTX GPUs
5. **Out of memory during processing**: Use `--processingonly 1` and `--processingthreadpct 0.1`

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

## Architecture Overview

### Core Application Structure
- **Main Application**: `LodClusters` class in `src/lodclusters.hpp/cpp` - primary application element
- **Scene Management**: `Scene` class handles 3D model loading, cluster generation, and geometry processing
- **Rendering**: Dual rendering paths for rasterization (`RendererRasterClustersLod`) and ray tracing (`RendererRayTraceClustersLod`)
- **Resources**: `Resources` class manages Vulkan resources, buffers, and memory allocation

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

### Known Build Patches Needed
1. **nvpro_core2 logger.cpp**: Add `#include <unistd.h>` after `#include <signal.h>` in the Unix section
   - Location: `build/_deps/nvpro_core2/nvutils/logger.cpp` around line 38-39
   - Error: `'isatty' was not declared in this scope`
   - Solution: Insert `#include <unistd.h>` after line with `#include <signal.h>`
2. **Anaconda conflicts**: Deactivate conda environment if encountering GLIBC linking errors
   - Use `conda deactivate` before building
   - Set clean PATH environment: `PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"`
   - Errors: `undefined reference to log2@GLIBC_2.29`, `__clock_getres@GLIBC_PRIVATE`

### Runtime Issues
- **Crash on startup**: Use `--renderer 0 --validation 0` for maximum compatibility
- **Out of memory during processing**: Use `--processingonly 1 --processingthreadpct 0.1`
- **Poor performance**: Disable validation with `--validation 0`
- **Ray tracing not working**: Requires RTX GPU and driver 572.16+, fallback to `--renderer 0`

### Performance Optimization
- Use Release builds for performance testing
- Disable validation layers in production: `--validation 0`
- For large scenes, process once with `--processingonly 1`, then run normally
- Adjust grid copies for memory constraints: `--gridcopies 1`
- Use memory mapping for very large cached scenes: `--mappedcache 1`

## Python Integration (VK2Torch)

### Overview
The codebase includes a Python integration system that enables zero-copy access to rendered frames from Python/PyTorch via Unix Domain Sockets and CUDA external memory. This allows real-time camera control and frame capture for AI/ML applications.

### Architecture Components
- **ExternalMemoryManager** (`src/external_memory.*`): Manages Vulkan external memory resources, timeline semaphores, and UDS communication
- **Python Client** (`python/vk2torch_client.py`): CUDA-enabled client for zero-copy tensor access
- **Integration Tests** (`python/test_integration.py`): Comprehensive test suite for the pipeline

### Key Integration Points
- **FrameConfig**: Extended with `externalMemoryManager` pointer to enable per-frame external memory operations
- **Renderers**: Both raster and ray tracing renderers include image-to-buffer copy operations after rendering
- **Main Application**: Extended with `--uds` and `--offscreen` CLI parameters for Python integration mode

### Usage Commands
```bash
# Enable Python integration mode
./_bin/Release/vk_lod_clusters --uds /tmp/vk2torch.sock --offscreen 1 --renderer 0 --validation 0

# Run Python integration tests
cd python && python test_integration.py

# Python client example
from vk2torch_client import VK2TorchClient
with VK2TorchClient() as client:
    client.connect()
    tensor = client.get_frame()  # Zero-copy PyTorch tensor
```

### Technical Details
- **Zero-Copy Pipeline**: Uses Vulkan external memory (`VK_KHR_external_memory_fd`) and timeline semaphores (`VK_KHR_timeline_semaphore`) for GPU-to-GPU data transfer
- **Synchronization**: Timeline semaphores coordinate camera parameter updates and frame completion between Python and Vulkan
- **Data Format**: R8G8B8A8_UNORM images with proper row pitch alignment for CUDA tensor mapping
- **Memory Management**: Exportable device-local buffers for camera parameters and color readback