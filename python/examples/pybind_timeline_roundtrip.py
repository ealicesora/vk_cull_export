#!/usr/bin/env python3
"""
Pybind11 Timeline Roundtrip Example
端到端时间线信号量握手版本

This example demonstrates the complete zero-copy depth rendering pipeline using:
1. pybind11 extension for direct Vulkan integration (no sockets)
2. Timeline semaphore coordination for frame synchronization  
3. CUDA external memory import for zero-copy depth access
4. Orbital camera motion with 1000 frame capture

Integration Flow:
1. Python creates Vk2TorchApp → Vulkan initializes → signalSceneReady(1)
2. Python imports all FDs → CUDA external memory/semaphore setup
3. Python waits scene_ready ≥ 1 → Vulkan ready for camera data
4. Frame loop: set_camera_matrices() → signal camera_ready=N → wait frame_done=N → decode depth
"""

import os
import sys
import time
import math
import numpy as np



import numpy as np

def _frustum_offcenter_rh_zo(l, r, b, t, n, f):
    # 右手、深度 0..1（与 glm::perspectiveRH_ZO 一致）
    P = np.array([
        [2*n/(r-l),      0.0,      (r+l)/(r-l),          0.0],
        [0.0,        2*n/(t-b),    (t+b)/(t-b),          0.0],
        [0.0,            0.0,          f/(n-f),    (f*n)/(n-f)],
        [0.0,            0.0,            -1.0,          0.0],
    ], dtype=np.float32)
    return P

def proj_from_intrinsics_vulkan(fx, fy, cx, cy, W, H, znear, zfar, *, flip_y=True):
    # 近裁面上的 frustum 边界（相机坐标系 y↑、z 向里前提下）
    l = -znear * (cx)      / fx
    r =  znear * (W - cx)  / fx
    t =  znear * (cy)      / fy
    b = -znear * (H - cy)  / fy
    P = _frustum_offcenter_rh_zo(l, r, b, t, znear, zfar)
    if flip_y:                      # ★ Vulkan 常用：在投影里翻一次 Y
        P[1, :] *= -1.0
    return P

def to_vulkan_viewproj_match_nvdiffrast(
    R_ocv, T_ocv,           # 同一组输入 R,T（world->cam，OpenCV/Colmap 约定）
    fx, fy, cx, cy, W, H, znear, zfar,
    *,
    nvdiffrast_world_is_z_up=True,   # 如果 nv 那边是 Z-up，而你的世界/Y-up，需要做基变换
    your_world_is_y_up=False
):
    R_ocv = np.swapaxes(R_ocv, -1, -2)
    R = np.asarray(R_ocv, np.float32)
    t = np.asarray(T_ocv, np.float32).reshape(3,1)

    # (可选) 基变换：把 Z-up 的世界坐标“翻译”为你这边的 Y-up
    # A = Rx(+90°) : (x, y, z)_nv -> (x, z, -y)_your
    # 对 world->cam：改变“世界基” => R' = R * A^{-1} = R * A^T
    if nvdiffrast_world_is_z_up and your_world_is_y_up:
        A = np.array([[1,0,0],
                      [0,0,1],
                      [0,-1,0]], dtype=np.float32)  # Rx(+90°)
        R = R @ A.T
        # t 不需要绕原点的基变换；如果你的世界原点与 nv 的不一致，再单独处理平移

    # OpenCV/Colmap(x→,y↓,z→) -> GL/Vulkan 相机系(x→,y↑,z里)
    S = np.diag([1.0, -1.0, -1.0]).astype(np.float32)
    R_cam = S @ R
    t_cam = S @ t

    view = np.eye(4, dtype=np.float32)
    view[:3,:3] = R_cam
    view[:3, 3] = t_cam.ravel()

    # 投影：为了与 nvdiffrast（OpenGL 栈）对齐且在 Vulkan 正显，翻一次 Y
    proj = proj_from_intrinsics_vulkan(fx, fy, cx, cy, W, H, znear, zfar, flip_y=True)

    # 以列主序展平给 Vulkan（和 glm::mat4(...) 构造一致）
    return view.T.ravel(), proj.T.ravel()




# Add parent directory to path for vk2torch_cuda import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import cupy as cp
    import torch
    print(f"✅ CuPy {cp.__version__}, PyTorch {torch.__version__}")
except ImportError as e:
    print(f"❌ Required library missing: {e}")
    print("Please install: conda activate vk2torch")
    sys.exit(1)

# Import our modules
try:
    # Add build directory to path for vk2torch_ext
    build_paths = [
        "build-py/_bin/Release",
        # "_bin/Release", 
        # "python/_bin/Release"
    ]
    for path in build_paths:
        if os.path.exists(path):
            sys.path.insert(0, path)
            break
    
    import vk2torch_ext as ext
    from vk2torch_cuda import (
        import_ext_memory_fd, import_timeline_semaphore_fd,
        wait_timeline, signal_timeline,
        make_pitched_cupy_array, depth_d24_to_float
    )
    print("✅ VK2Torch modules imported successfully")
    
except ImportError as e:
    print(f"❌ VK2Torch module import failed: {e}")
    print("Please build the pybind11 extension first:")
    print("  cmake -S . -B build-py -DCMAKE_TOOLCHAIN_FILE=toolchains/system_no_conda.cmake -DBUILD_PYTHON_EXT=ON")
    print("  cmake --build build-py --config Release -j4")
    sys.exit(1)

# Configuration
W, H = 1024, 1024
ASSET_ROOT = os.getcwd()  # Current working directory
N_FRAMES = 1000

def make_camera_matrices(frame_num: int) -> tuple:
    """
    Generate orbital camera matrices for given frame
    
    Args:
        frame_num: Frame number for animation
        
    Returns:
        Tuple of (projection_matrix, view_matrix) as float32 numpy arrays (row-major)
    """
    # Orbital camera parameters
    t = frame_num * (2.0 * math.pi / N_FRAMES)  # Complete orbit over N_FRAMES
    radius = 3.0
    height = 1.5
    
    # Camera position (orbital motion)
    eye = np.array([
        math.cos(t) * radius,
        height, 
        math.sin(t) * radius
    ], dtype=np.float32)
    
    # Look at center
    center = np.array([0.0, 0.5, 0.0], dtype=np.float32)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    
    # Build view matrix (right-handed, column-major internally, then convert to row-major)
    def normalize(v):
        norm = np.linalg.norm(v)
        return v / (norm + 1e-8)
    
    f = normalize(center - eye)  # Forward
    s = normalize(np.cross(f, up))  # Right  
    u = np.cross(s, f)  # Up
    
    # View matrix (column-major)
    view_col_major = np.eye(4, dtype=np.float32)
    view_col_major[0, :3] = s
    view_col_major[1, :3] = u
    view_col_major[2, :3] = -f
    view_col_major[:3, 3] = -view_col_major[:3, :3] @ eye
    
    # Perspective projection matrix (column-major)  
    fovy = math.radians(60.0)
    aspect = float(W) / float(H)
    near, far = 0.1, 100.0
    
    f_val = 1.0 / math.tan(fovy / 2.0)
    proj_col_major = np.zeros((4, 4), dtype=np.float32)
    proj_col_major[0, 0] = f_val / aspect
    proj_col_major[1, 1] = f_val
    proj_col_major[2, 2] = far / (far - near)
    proj_col_major[2, 3] = (-far * near) / (far - near)
    proj_col_major[3, 2] = 1.0
    
    # Convert to row-major for pybind11 (it will convert back to column-major internally)
    proj_row_major = proj_col_major.T
    view_row_major = view_col_major.T
    
    return proj_row_major, view_row_major

def main():
    """Main timeline semaphore roundtrip example"""
    
    print("🎬 Pybind11 Timeline Roundtrip Example")
    print("=" * 60)
    
    try:
        # 1) Create Vk2TorchApp with real 3D rendering
        print(f"📱 Creating Vk2TorchApp ({W}x{H}) with asset root: {ASSET_ROOT}")
        app = ext.Vk2TorchApp(W, H, True, "", ASSET_ROOT)  # raster=True, no scene override, use asset root
        print("✅ Vk2TorchApp created successfully")
        
        # 2) Get complete interop info with all FDs (duplicated for Python ownership)
        print("📋 Getting interop export information...")
        info = app.get_interop_info()
        print("✅ Interop info retrieved:")
        for key, value in info.items():
            if 'fd' in key:
                print(f"    {key}: {value} (FD)")
            else:
                print(f"    {key}: {value}")
        
        # 3) Import all CUDA resources from file descriptors
        print("🔗 Importing CUDA external resources...")

        time.sleep(1.0)

        # Import external memory and get device pointer

        buffer_size = int(info['height']) * int(info['row_pitch_bytes'])
        ext_mem, dev_ptr = import_ext_memory_fd(int(info['depth_mem_fd']), buffer_size)
        print(f"✅ Depth memory imported: {buffer_size} bytes")
        
        # Import timeline semaphores  
        
        sem_scene = import_timeline_semaphore_fd(int(info['scene_ready_sem_fd']))
        sem_camera = import_timeline_semaphore_fd(int(info['camera_ready_sem_fd']))
        sem_frame = import_timeline_semaphore_fd(int(info['frame_done_sem_fd']))
        print("✅ Timeline semaphores imported")
        
        # NO need to Close FDs !!!!
        # for fd_key in ['depth_mem_fd', 'scene_ready_sem_fd', 'camera_ready_sem_fd', 'frame_done_sem_fd']:
        #     fd_val = int(info[fd_key])
        #     if fd_val >= 0:
        #         os.close(fd_val)
        
        width = int(info['width'])
        height = int(info['height']) 
        pitch = int(info['row_pitch_bytes'])
        
        # 4) Wait for Vulkan scene ready (scene_ready >= 1)
        print("⏳ Waiting for Vulkan scene initialization...")
        stream = cp.cuda.Stream(non_blocking=True)
        
        # with stream:
        #     wait_timeline(sem_scene, 1, stream.ptr)
        cp.cuda.Stream.null.synchronize()
        print("✅ Scene ready - Vulkan rendering pipeline initialized")
        
        # 5) Set up CuPy view of depth buffer (pitched for proper row alignment)
        print(f"🖼️  Creating depth buffer view: {width}x{height}, pitch={pitch}")
        
        # Create pitched array view (full width including padding)
        u32_pitched = make_pitched_cupy_array(dev_ptr.value, pitch, width, height, np.uint32)
        
        # Slice to actual image dimensions (remove row padding)
        u32 = u32_pitched[:, :width] 
        
        print("✅ Depth buffer CuPy view created")
        
        # 6) Frame rendering loop with timeline semaphore coordination
        print(f"🎥 Starting {N_FRAMES} frame rendering loop...")
        print("    Timeline coordination: set_camera_matrices() → signal camera_ready=N → wait frame_done=N")
        
        os.makedirs("out_depth", exist_ok=True)
        
        
        
        app.headless_init()

        start_time = time.time()
        for frame_num in range(1, N_FRAMES + 1):
            # 6.1) Generate camera matrices for orbital motion
            proj_matrix, view_matrix = make_camera_matrices(frame_num)
            
            # 6.2) Set camera matrices via pybind11 (triggers camera ready signal internally)
            app.set_camera_matrices(proj_matrix, view_matrix)
            
            
            app.headless_step()
            # time.sleep(1.0)
            
            # 6.5) Process and save depth frame
            depth_float = depth_d24_to_float(u32)  # Convert D24 to float32 [0,1]
            
            # Save selected frames
            # if frame_num % 100 == 0 or frame_num <= 10 or frame_num > N_FRAMES - 10:
            #     # Copy to CPU for saving
            #     depth_cpu = cp.asnumpy(depth_float)
            #     np.save(f"out_depth/depth_{frame_num:04d}.npy", depth_cpu)
                
            #     # Calculate statistics
            #     valid_mask = depth_cpu > 0.0
            #     if np.any(valid_mask):
            #         min_depth = np.min(depth_cpu[valid_mask])
            #         max_depth = np.max(depth_cpu[valid_mask])
            #         mean_depth = np.mean(depth_cpu[valid_mask])
            #         print(f"📸 Frame {frame_num:4d}: depth range [{min_depth:.3f}, {max_depth:.3f}], mean={mean_depth:.3f} - saved")
            #     else:
            #         print(f"📸 Frame {frame_num:4d}: no valid depth data - saved")
            
            # Progress indicator  
            if frame_num % 50 == 0:
                elapsed = time.time() - start_time
                fps = frame_num / elapsed
                eta = (N_FRAMES - frame_num) / fps if fps > 0 else 0
                print(f"⏱️  Progress: {frame_num}/{N_FRAMES} ({100*frame_num/N_FRAMES:.1f}%) - {fps:.1f} FPS - ETA: {eta:.1f}s")
        
        # Final synchronization
        cp.cuda.Stream.null.synchronize()
        
        # 7) Summary and cleanup
        total_time = time.time() - start_time
        avg_fps = N_FRAMES / total_time
        
        print("=" * 60)
        print("🎉 Timeline Roundtrip Complete!")
        print(f"📊 Performance Summary:")
        print(f"    • Total frames: {N_FRAMES}")
        print(f"    • Total time: {total_time:.2f} seconds") 
        print(f"    • Average FPS: {avg_fps:.2f}")
        print(f"    • Frame time: {1000/avg_fps:.2f} ms/frame")
        print(f"📁 Depth frames saved to: out_depth/")
        print(f"    • Saved frames: {len([f for f in os.listdir('out_depth') if f.endswith('.npy')])}")
        
        # Stop application
        print("🛑 Stopping Vk2TorchApp...")
        app.stop()
        print("✅ Application stopped")
        
    except Exception as e:
        print(f"❌ Timeline roundtrip failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    print("VK2Torch Pybind11 Timeline Roundtrip")
    print("零拷贝深度渲染时间线信号量端到端测试")
    print("=" * 80)
    
    # Verify environment
    print("🔍 Environment check:")
    
    # Check CUDA availability
    if not cp.cuda.is_available():
        print("❌ CUDA not available")
        sys.exit(1)
    print(f"✅ CUDA available - device count: {cp.cuda.runtime.getDeviceCount()}")
    
    # Check PyTorch CUDA
    if not torch.cuda.is_available():
        print("❌ PyTorch CUDA not available")
        sys.exit(1)
    print(f"✅ PyTorch CUDA available - device: {torch.cuda.get_device_name()}")
    
    print()
    main()
    
