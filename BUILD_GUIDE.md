# VK LOD Clusters - Complete Build Guide

This document contains the complete steps to successfully build the VK LOD Clusters project, including all fixes and patches applied.

## Prerequisites

- **Vulkan SDK 1.4.309.0 or later** (we used 1.4.321.1)
- **CMake 3.22+**
- **GCC 10.5.0 or later** (GCC 9.4.0 has C++20 compatibility issues)
- **Git** (for submodules)

## Hardware Requirements

- **GPU**: NVIDIA GTX 1660 Ti or better (RTX series recommended for ray tracing)
- **RAM**: 8GB+ (16GB+ recommended for large scenes)
- **Storage**: ~2GB for build artifacts

## Build Steps

### 1. Clone and Initialize Submodules
```bash
cd /path/to/project
git submodule update --init --recursive
```

### 2. Clean Previous Build (if exists)
```bash
rm -rf build _bin
```

### 3. Configure CMake with Proper Compiler
**Important**: Use GCC-10 instead of default GCC-9 for proper C++20 support:

```bash
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF
```

**Key Configuration Options:**
- `DCMAKE_BUILD_TYPE=Release` - Release build for performance
- `DUSE_DLSS=OFF` - Disable DLSS (we don't need it)
- `CC=gcc-10 CXX=g++-10` - Use GCC-10 for C++20 compatibility

### 4. Apply Required Patches

#### Patch 1: Fix Missing Header in nvpro_core2
```bash
# Add missing unistd.h header
echo '#include <unistd.h>' >> build/_deps/nvpro_core2/nvutils/logger.cpp
```

**Or manually edit** `build/_deps/nvpro_core2/nvutils/logger.cpp`:
```cpp
#elif defined(__unix__)
#include <signal.h>
#include <unistd.h>  // Add this line
#endif
```

#### Patch 2: Add Pthread Linking
**Edit** `CMakeLists.txt`, add after line 13:
```cmake
find_package(Threads REQUIRED)
```

**And in target_link_libraries section** (around line 48):
```cmake
target_link_libraries(${PROJECT_NAME} PRIVATE
  nvpro2::nvapp
  nvpro2::nvgui
  nvpro2::nvutils
  nvpro2::nvvk
  nvpro2::nvvkglsl
  nv_cluster_lod_builder
  meshoptimizer
  cgltf
  Threads::Threads  # Add this line
)
```

#### Patch 3: Make Ray Tracing Extensions Optional (for non-RTX GPUs)
**Edit** `src/main.cpp` around lines 74-85, add `, false` parameter:
```cpp
vkSetup.deviceExtensions.push_back({VK_KHR_DEFERRED_HOST_OPERATIONS_EXTENSION_NAME, nullptr, false});
vkSetup.deviceExtensions.push_back({VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME, &accKHR, false});
vkSetup.deviceExtensions.push_back({VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME, &rayKHR, false});
vkSetup.deviceExtensions.push_back({VK_KHR_RAY_TRACING_POSITION_FETCH_EXTENSION_NAME, &rayPosKHR, false});
vkSetup.deviceExtensions.push_back({VK_KHR_RAY_QUERY_EXTENSION_NAME, &rayQueryKHR, false});
vkSetup.deviceExtensions.push_back({VK_KHR_SHADER_CLOCK_EXTENSION_NAME, &clockKHR, false});
vkSetup.deviceExtensions.push_back({VK_EXT_SHADER_ATOMIC_FLOAT_EXTENSION_NAME, &atomicFloatFeatures, false});
vkSetup.deviceExtensions.push_back({VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME, &shadingRateFeatures, false});
vkSetup.deviceExtensions.push_back({VK_KHR_FRAGMENT_SHADER_BARYCENTRIC_EXTENSION_NAME, &barycentricFeatures, false});
vkSetup.deviceExtensions.push_back({VK_NV_SHADER_SUBGROUP_PARTITIONED_EXTENSION_NAME, nullptr, false});
```

#### Patch 4: Fix Grid Copy Override (for single bunny support)
**Edit** `src/lodclusters.cpp` around lines 402-412, comment out the auto-grid logic:
```cpp
// Comment out the automatic grid setup to respect user's --gridcopies parameter
/*
if(m_sceneGridConfig.numCopies == 1)
{
  if(m_resources.getDeviceLocalHeapSize() >= 8ull * 1024 * 1024 * 1024)
  {
    m_sceneGridConfig.numCopies = 1024;  // 32x32 grid
  }
  else
  {
    m_sceneGridConfig.numCopies = 64;
  }
}
*/
```

### 5. Build the Project
```bash
cmake --build build --config Release -j$(nproc)
```

**Expected Output:**
- 100+ targets should build successfully
- Final executable: `_bin/Release/vk_lod_clusters` (~7.3MB)

### 6. Verify Build Success
```bash
ls -la _bin/Release/
file _bin/Release/vk_lod_clusters
./_bin/Release/vk_lod_clusters --help
```

## Running the Application

### Basic Commands

**Single Bunny (Rasterization Mode):**
```bash
./_bin/Release/vk_lod_clusters --renderer 0 --validation 0 --gridcopies 1
```

**Large Scene Processing (Memory-Efficient):**
```bash
# First pass: Process geometry only
./_bin/Release/vk_lod_clusters --scene city.gltf --processingonly 1 --processingthreadpct 0.1

# Second pass: Run with cached data
./_bin/Release/vk_lod_clusters --scene city.gltf --renderer 0 --validation 0 --gridcopies 1
```

### Key Parameters

**Memory Management:**
- `--processingonly 1` - Process and cache only, reduces peak memory
- `--processingthreadpct 0.1` - Use 10% of CPU threads (less parallel memory usage)
- `--mappedcache 1` - Use memory-mapped cache files
- `--gridcopies 1` - Single instance instead of grid

**Rendering:**
- `--renderer 0` - Rasterization mode (works on non-RTX GPUs)
- `--renderer 1` - Ray tracing mode (requires RTX GPU)
- `--validation 0` - Disable Vulkan validation for performance

## Troubleshooting

### Common Issues

**1. "Extension not available" Error:**
- **Solution:** Ray tracing extensions patch applied (Patch 3)
- Use `--renderer 0` for non-RTX GPUs

**2. "SIGTRAP" or Crash on Startup:**
- **Solution:** All patches applied correctly
- Check that extensions are marked as optional (`false` parameter)

**3. "pthread_getspecific" Linking Error:**
- **Solution:** Pthread linking patch applied (Patch 2)

**4. "concepts: No such file" Compilation Error:**
- **Solution:** Use GCC-10 instead of GCC-9
- **Command:** `CC=gcc-10 CXX=g++-10 cmake ...`

**5. Out of Memory During Processing:**
- Use `--processingonly 1` first
- Reduce threads: `--processingthreadpct 0.1`
- Use single copy: `--gridcopies 1`

### Build Environment

**Successfully Tested On:**
- **OS:** Ubuntu 20.04 LTS (Linux 5.15.0-139-generic)
- **Compiler:** GCC 10.5.0
- **Vulkan:** SDK 1.4.321.1
- **GPU:** NVIDIA GeForce GTX 1660 Ti (driver 580.76.05)
- **RAM:** System with 8GB+ RAM

## Final Build Command Summary

**Complete build sequence:**
```bash
# 1. Clean and configure
rm -rf build _bin
CC=gcc-10 CXX=g++-10 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF

# 2. Apply patches (manual edits to files above)

# 3. Build
cmake --build build --config Release -j$(nproc)

# 4. Test
./_bin/Release/vk_lod_clusters --renderer 0 --validation 0 --gridcopies 1 --help
```

## Build Artifacts

**Generated Files:**
- **Executable:** `_bin/Release/vk_lod_clusters` (7.3MB)
- **Libraries:** `build/` directory (~2GB total)
- **Dependencies:** `build/_deps/` (nvpro_core2, etc.)

---
**Build completed successfully!** 🎉

*Last updated: Based on successful build with all patches applied*