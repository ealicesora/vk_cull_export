# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build System

### Primary Build Commands
```bash
# Configure build (creates build directory)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

# Build the project
cmake --build build --config Release

# For debug builds (includes more UI elements)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build --config Debug
```

### Dependencies
- Requires Vulkan SDK 1.4.309.0 or later
- Uses CMake 3.22+ with C++20 standard
- Automatically downloads nvpro_core2 framework if not found
- Optionally downloads DLSS SDK when USE_DLSS=ON

### Key CMake Options
- `USE_DLSS=ON/OFF` - Enable DLSS denoising (default ON)
- Build system automatically downloads Stanford Bunny glTF model as default scene

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
- `--renderer 0` - Start with rasterization mode
- `--streaming 0` - Disable streaming (preload all geometry)
- `--gridunique 0` - Reduce memory by true instancing
- `--clasallocator 0` - Use simple CLAS compaction instead of persistent allocator
- `--supersample 0` - Disable 2x super sampling
- `--autoloadcache 0/1` - Control cache file loading
- `--processingonly 1` - Process geometry and save cache, then exit

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