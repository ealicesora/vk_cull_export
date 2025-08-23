#!/usr/bin/env python3
"""Final test to check if everything works."""

import sys
import os
import time
import subprocess


import time
import csv
import statistics as stats
from time import perf_counter



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


# Add Python client path
sys.path.insert(0, 'python')

def test_system():
    """Complete system test with socket-based camera control."""
    
    # Test with the updated client (now using socket-based camera matrices)
    from vk2torch_client import VK2TorchClient
    import numpy as np
    
    print("\nConnecting with VK2TorchClient (socket-based camera protocol)...")
    client = VK2TorchClient('/tmp/vk2torch.sock')
    
    if client.connect():
        print(f"✅ Connected: {client.width}x{client.height}")
        print(f"   Format: {client.format}")
        print(f"   UUID: {client.vk_uuid}")
        print(f"   Connection status: {client.connection_status}")
        print("✅ Received 'ready to render' message from Vulkan")
        
        # Test with varying camera positions to show socket control works
        print("\nTesting frame capture with different camera positions...")
        
        t_all_start = perf_counter()
        frame = None
        
        for i in range(0, 1000):  
            distance = 4.0 + i * 0.5  

            R = np.array([[ 0.98822485,  0.11374114, -0.10234546],
                        [-0.11979481,  0.99127023, -0.05506844],
                        [ 0.09518846,  0.06668046,  0.99322348]], dtype=np.float32)
            T = np.array([-2.80552141, -1.27673587,  3.06543639], dtype=np.float32)
      

            Fx = 1208.1880959114053
            Fy = 1209.669871748316
 
            W  = 1000
            H  = 1000
            Cx = W / 2
            Cy = H / 2
            znear, zfar = 0.1, 1000.0




            view_flat, proj_flat = to_vulkan_viewproj_match_nvdiffrast(
                R, T, Fx, Fy, Cx, Cy, W, H, znear, zfar
            )

            # print(f"Frame {i}: update_camera (frame_number={client.frame_number}, distance={distance:.1f})")
            client.update_camera(view_flat, proj_flat)
            # print("✅ Camera matrices sent via socket")

            frame = client.get_frame(timeout_ms=2000)
            # def depth01_to_linear(depth01, znear, zfar):
            #     # 适用于 Vulkan/D3D 的 0..1 深度（非 reversed-Z）
            #     return (znear * zfar) / (zfar - depth01 * (zfar - znear))
            # frame = depth01_to_linear(frame,znear,zfar)
            # print(frame.sum())
            # if frame is not None:
            #     client.save_frame_png(frame, f"success_test{i}.png")
            #     print(f"✅ Frame {i} saved")
            # else:
            #     print(f"⚠️ Frame {i} capture failed")
            
        t_all = perf_counter() - t_all_start
        print(f"Total time for 600 frames: {t_all:.2f}s")
        time.sleep(10)
        if frame is not None:
            123
            # print(frame.sum())
            # print(f"✅ Got frame: {frame.shape if hasattr(frame, 'shape') else 'data received'}")
        else:
            print("⚠️ Frame capture not available (expected without CUDA)")
        
        client.disconnect()
        print("✅ Disconnected cleanly")
        
        return True
    else:
        print("❌ Connection failed")
        return False
        



if __name__ == "__main__":
    success = test_system()
    sys.exit(0 if success else 1)