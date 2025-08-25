#!/usr/bin/env python3
"""
VK2Torch Renderer Module

A reusable Python class for rendering 3D scenes using the VK2Torch extension.
Provides zero-copy depth buffer access via CUDA integration.
"""

import os
import sys
import time
import numpy as np
from typing import Tuple, Union, Optional, List
from pathlib import Path

# Add parent directory to path for module imports
current_dir = Path(__file__).parent
sys.path.append(str(current_dir.parent))

try:
    import cupy as cp
    import torch
    HAS_CUDA = True
except ImportError:
    HAS_CUDA = False
    cp = None
    torch = None

# Import VK2Torch modules
try:
    # Add build directory to path
    build_paths = [
        "build-py/_bin/Release",
        "_bin/Release",
        "python/_bin/Release"
    ]
    for path in build_paths:
        full_path = current_dir.parent / path
        if full_path.exists():
            sys.path.insert(0, str(full_path))
            break
    
    import vk2torch_ext as ext
    from vk2torch_cuda import (
        import_ext_memory_fd, import_timeline_semaphore_fd,
        make_pitched_cupy_array, depth_d24_to_float
    )
    HAS_VK2TORCH = True
except ImportError as e:
    HAS_VK2TORCH = False
    ext = None

# Import utilities
from vk2torch_utils import (
    to_vulkan_viewproj_match_nvdiffrast, 
    create_orbital_camera,
    save_depth_png,
    make_pitched_cupy_array as util_make_pitched_array
)

class VK2TorchRenderer:
    """
    High-level renderer class for VK2Torch integration.
    
    Provides an easy-to-use interface for rendering 3D scenes with programmable
    camera control and zero-copy depth buffer access.
    """
    
    def __init__(self, 
                 width: int, 
                 height: int,
                 scene_file: Union[str, Path],
                 asset_root: Union[str, Path], 
                 *,
                 use_raster: bool = True,
                 znear: float = 0.1,
                 zfar: float = 1000.0):
        """
        Initialize the VK2Torch renderer.
        
        Args:
            width, height: Render target dimensions
            scene_file: Path to scene file (relative to asset_root)
            asset_root: Root directory for assets (shaders, models, etc.)
            use_raster: Use rasterization (True) or ray tracing (False)
            znear, zfar: Near and far plane distances
        """
        # Validate dependencies
        if not HAS_CUDA:
            raise RuntimeError("CUDA libraries (CuPy, PyTorch) are required")
        if not HAS_VK2TORCH:
            raise RuntimeError("VK2Torch extension not found. Please build with: "
                             "cmake -S . -B build-py -DBUILD_PYTHON_EXT=ON && "
                             "cmake --build build-py --config Release")
        
        # Store configuration
        self.width = width
        self.height = height
        self.scene_file = Path(scene_file)
        self.asset_root = Path(asset_root)
        self.use_raster = use_raster
        self.znear = znear
        self.zfar = zfar
        
        # State tracking
        self._app = None
        self._initialized = False
        self._cuda_resources_ready = False
        self._frame_count = 0
        
        # CUDA resources (initialized lazily)
        self._ext_mem = None
        self._dev_ptr = None
        self._sem_scene = None
        self._sem_camera = None
        self._sem_frame = None
        self._depth_array = None
        
        # Interop info
        self._interop_info = None
        
        print(f"VK2TorchRenderer initialized: {width}x{height}, scene: {scene_file}")
    
    def _init_vulkan_app(self):
        """Initialize the Vulkan application."""
        if self._app is not None:
            return
            
        print(f"Creating Vulkan app with scene: {self.scene_file}")
        print(f"Asset root: {self.asset_root}")
        
        # Create Vk2TorchApp
        self._app = ext.Vk2TorchApp(
            self.width, 
            self.height, 
            self.use_raster,
            str(self.scene_file),
            str(self.asset_root)
        )
        
        print("✅ Vulkan app created successfully")
        self._initialized = True
    
    def _init_cuda_resources(self):
        """Initialize CUDA external memory resources."""
        if self._cuda_resources_ready or self._app is None:
            return
            
        print("Initializing CUDA resources...")
        
        # Get interop info
        self._interop_info = self._app.get_interop_info()
        
        # Import external memory
        buffer_size = int(self._interop_info['height']) * int(self._interop_info['row_pitch_bytes'])
        self._ext_mem, self._dev_ptr = import_ext_memory_fd(
            int(self._interop_info['depth_mem_fd']), 
            buffer_size
        )
        
        # Import timeline semaphores
        self._sem_scene = import_timeline_semaphore_fd(int(self._interop_info['scene_ready_sem_fd']))
        self._sem_camera = import_timeline_semaphore_fd(int(self._interop_info['camera_ready_sem_fd']))
        self._sem_frame = import_timeline_semaphore_fd(int(self._interop_info['frame_done_sem_fd']))
        
        # Create depth buffer view
        width = int(self._interop_info['width'])
        height = int(self._interop_info['height'])
        pitch = int(self._interop_info['row_pitch_bytes'])
        
        # Create pitched array
        try:
            # Try using the imported function first
            u32_pitched = make_pitched_cupy_array(
                self._dev_ptr.value, pitch, width, height, np.uint32
            )
        except:
            # Fallback to utility function
            u32_pitched = util_make_pitched_array(
                self._dev_ptr.value, pitch, width, height, np.uint32
            )
        
        # Slice to actual image dimensions
        self._depth_array = u32_pitched[:, :width]
        
        print(f"✅ CUDA resources initialized: {width}x{height}, pitch={pitch}")
        self._cuda_resources_ready = True
    
    def render(self,
              camera_R: Optional[np.ndarray] = None,
              camera_T: Optional[np.ndarray] = None,
              *,
              fx: Optional[float] = None,
              fy: Optional[float] = None,
              cx: Optional[float] = None,
              cy: Optional[float] = None,
              orbital_frame: Optional[int] = None,
              orbital_radius: float = 5.0,
              orbital_height: float = 2.0,
              return_cpu: bool = False) -> Union[cp.ndarray, np.ndarray]:
        """
        Render a frame with the specified camera parameters.
        
        Args:
            camera_R: 3x3 rotation matrix (world -> camera)
            camera_T: 3-element translation vector (world -> camera)
            fx, fy: Camera focal lengths (pixels)
            cx, cy: Camera principal point (pixels)
            orbital_frame: If provided, use orbital motion instead of R/T
            orbital_radius: Radius for orbital motion
            orbital_height: Height for orbital motion
            return_cpu: Return result as NumPy array (CPU) instead of CuPy (GPU)
            
        Returns:
            Depth buffer as CuPy array (GPU) or NumPy array (CPU)
        """
        # Initialize if needed
        if not self._initialized:
            self._init_vulkan_app()
            
        if not self._cuda_resources_ready:
            self._init_cuda_resources()
            
        # Initialize Vulkan app for headless rendering
        if self._frame_count == 0:
            self._app.headless_init()
            # Compile depth conversion operator
            _ = depth_d24_to_float(self._depth_array)
            cp.cuda.Stream.null.synchronize()
            time.sleep(0.1)  # Small delay for initialization
        
        # Determine camera parameters
        if orbital_frame is not None:
            # Use orbital motion
            camera_R, camera_T = create_orbital_camera(
                orbital_frame, orbital_radius, orbital_height
            )
            
        if camera_R is None or camera_T is None:
            raise ValueError("Must provide either (camera_R, camera_T) or orbital_frame")
        
        # Set default intrinsics if not provided
        if fx is None:
            fx = self.width * 0.8  # Reasonable default
        if fy is None:
            fy = fx  # Square pixels
        if cx is None:
            cx = self.width / 2
        if cy is None:
            cy = self.height / 2
            
        # Convert to Vulkan matrices
        view_flat, proj_flat = to_vulkan_viewproj_match_nvdiffrast(
            camera_R, camera_T, fx, fy, cx, cy, 
            self.width, self.height, self.znear, self.zfar
        )
        
        proj_matrix = proj_flat.reshape([4, 4])
        view_matrix = view_flat.reshape([4, 4])
        
        # Set camera matrices and render
        self._app.set_camera_matrices(proj_matrix, view_matrix)
        self._app.headless_step()
        
        # Convert depth buffer
        depth_float = depth_d24_to_float(self._depth_array)
        
        self._frame_count += 1
        
        # Return as requested type
        if return_cpu:
            return cp.asnumpy(depth_float)
        else:
            return depth_float
    
    def render_batch(self,
                    camera_params_list: List[dict],
                    *,
                    return_cpu: bool = False,
                    show_progress: bool = True) -> List[Union[cp.ndarray, np.ndarray]]:
        """
        Render multiple frames with different camera parameters.
        
        Args:
            camera_params_list: List of dictionaries with camera parameters
            return_cpu: Return results as NumPy arrays instead of CuPy
            show_progress: Show progress during batch rendering
            
        Returns:
            List of depth arrays
        """
        results = []
        total_frames = len(camera_params_list)
        
        start_time = time.time()
        
        for i, params in enumerate(camera_params_list):
            depth = self.render(return_cpu=return_cpu, **params)
            results.append(depth)
            
            if show_progress and (i % 10 == 0 or i == total_frames - 1):
                elapsed = time.time() - start_time
                fps = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (total_frames - i - 1) / fps if fps > 0 else 0
                progress = (i + 1) / total_frames * 100
                print(f"Progress: {i+1}/{total_frames} ({progress:.1f}%) - "
                      f"{fps:.1f} FPS - ETA: {eta:.1f}s")
        
        return results
    
    def get_depth_cpu(self) -> np.ndarray:
        """Get the current depth buffer as a CPU NumPy array."""
        if not self._cuda_resources_ready:
            raise RuntimeError("CUDA resources not initialized. Call render() first.")
        
        depth_float = depth_d24_to_float(self._depth_array)
        return cp.asnumpy(depth_float)
    
    def save_depth(self, 
                   filename: Union[str, Path],
                   *,
                   normalize: bool = True,
                   format: str = 'png') -> bool:
        """
        Save the current depth buffer to file.
        
        Args:
            filename: Output filename
            normalize: Normalize depth values to [0,1] range
            format: Output format ('png' or 'npy')
            
        Returns:
            True if save was successful
        """
        if not self._cuda_resources_ready:
            raise RuntimeError("CUDA resources not initialized. Call render() first.")
        
        depth_cpu = self.get_depth_cpu()
        
        if format.lower() == 'npy':
            np.save(filename, depth_cpu)
            return True
        else:
            return save_depth_png(depth_cpu, str(filename), normalize=normalize)
    
    def create_orbital_sequence(self,
                              num_frames: int,
                              *,
                              radius: float = 5.0,
                              height: float = 2.0,
                              fx: Optional[float] = None,
                              fy: Optional[float] = None,
                              return_cpu: bool = False) -> List[Union[cp.ndarray, np.ndarray]]:
        """
        Create an orbital camera sequence.
        
        Args:
            num_frames: Number of frames to render
            radius: Orbital radius
            height: Camera height
            fx, fy: Camera focal lengths
            return_cpu: Return as NumPy arrays
            
        Returns:
            List of depth arrays
        """
        camera_params = []
        
        for frame in range(num_frames):
            params = {
                'orbital_frame': frame,
                'orbital_radius': radius,
                'orbital_height': height
            }
            
            if fx is not None:
                params['fx'] = fx
            if fy is not None:
                params['fy'] = fy
                
            camera_params.append(params)
        
        return self.render_batch(camera_params, return_cpu=return_cpu)
    
    def get_info(self) -> dict:
        """Get information about the renderer and current state."""
        return {
            'width': self.width,
            'height': self.height,
            'scene_file': str(self.scene_file),
            'asset_root': str(self.asset_root),
            'use_raster': self.use_raster,
            'znear': self.znear,
            'zfar': self.zfar,
            'initialized': self._initialized,
            'cuda_ready': self._cuda_resources_ready,
            'frame_count': self._frame_count,
            'interop_info': self._interop_info
        }
    
    def close(self):
        """Clean up resources."""
        if self._app is not None:
            try:
                self._app.stop()
            except:
                pass
            self._app = None
        
        # Reset state
        self._initialized = False
        self._cuda_resources_ready = False
        self._frame_count = 0
        
        # Clear CUDA resources
        self._ext_mem = None
        self._dev_ptr = None
        self._sem_scene = None
        self._sem_camera = None
        self._sem_frame = None
        self._depth_array = None
        
        print("VK2TorchRenderer resources cleaned up")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def __del__(self):
        """Destructor - ensure cleanup."""
        try:
            self.close()
        except:
            pass


# Convenience functions for quick usage
def quick_render(scene_file: str,
                asset_root: str = ".",
                *,
                width: int = 1000,
                height: int = 1000,
                orbital_frames: int = 10,
                save_dir: str = "output") -> List[np.ndarray]:
    """
    Quick rendering function for simple use cases.
    
    Args:
        scene_file: Path to scene file
        asset_root: Asset root directory
        width, height: Render dimensions
        orbital_frames: Number of orbital motion frames
        save_dir: Directory to save depth images
        
    Returns:
        List of depth arrays
    """
    os.makedirs(save_dir, exist_ok=True)
    
    with VK2TorchRenderer(width, height, scene_file, asset_root) as renderer:
        depths = renderer.create_orbital_sequence(
            orbital_frames, return_cpu=True
        )
        
        # Save depth images
        for i, depth in enumerate(depths):
            filename = os.path.join(save_dir, f"depth_{i:04d}.png")
            save_depth_png(depth, filename)
        
        print(f"Saved {len(depths)} depth images to {save_dir}")
        return depths


if __name__ == "__main__":
    # Simple test
    print("VK2TorchRenderer test")
    
    # Test with default scene
    try:
        depths = quick_render(
            scene_file="house_new.glb",
            asset_root=".",
            orbital_frames=5
        )
        print(f"✅ Test successful: rendered {len(depths)} frames")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()