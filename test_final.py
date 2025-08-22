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


def _frustum_offcenter_rh_zo(l, r, b, t, n, f):
    # 右手、深度 0..1（与 glm::perspectiveRH_ZO 一致）
    P = np.array([
        [2*n/(r-l),      0.0,      (r+l)/(r-l),          0.0],
        [0.0,        2*n/(t-b),    (t+b)/(t-b),          0.0],
        [0.0,            0.0,          f/(n-f),    (f*n)/(n-f)],
        [0.0,            0.0,            -1.0,          0.0],
    ], dtype=np.float32)
    return P

def opencv_extrinsics_to_view_vulkan(R, t, *, is_world_to_cam=True, do_yz_flip=True):
    """
    R, t 来自 OpenCV/COLMAP。
    - is_world_to_cam=True：R,t 满足 X_cam = R X_world + t（多数工具默认）
      如果你手上是 c2w，请设为 False。
    - do_yz_flip=True：OpenCV(x右,y下,z前) -> GL/Vulkan(x右,y上,z里)
    返回：4x4 view（world->camera），适配 GL/Vulkan 相机系。
    """
    R = np.asarray(R, np.float32)
    t = np.asarray(t, np.float32).reshape(3, 1)

    if not is_world_to_cam:
        # 输入是 c2w，先转 w2c
        R_wc = R.T
        t_wc = -R_wc @ t
        R, t = R_wc, t_wc

    if do_yz_flip:
        S = np.diag([1.0, -1.0, -1.0]).astype(np.float32)  # y,z 取反
        R = S @ R
        t = S @ t

    view = np.eye(4, dtype=np.float32)
    view[:3, :3] = R
    view[:3,  3] = t.ravel()
    return view

def opencv_intrinsics_to_proj_vulkan(fx, fy, cx, cy, W, H, znear, zfar, *, do_vulkan_y_flip=True):
    """
    用内参构造离轴透视投影（RH_ZO），并按需做 Vulkan 的 Y 翻转（== 只翻一次）。
    这里假设像素原点在左上，OpenCV 的 (cx,cy) 也是以左上为原点。
    """
    # 近裁面上的 frustum 边界（已经在相机为 y↑、z 向里后成立）
    l = -znear * (cx)      / fx
    r =  znear * (W - cx)  / fx
    t =  znear * (cy)      / fy
    b = -znear * (H - cy)  / fy

    proj = _frustum_offcenter_rh_zo(l, r, b, t, znear, zfar)

    # proj[0, :] *= -1.0 

    if do_vulkan_y_flip:
        # 等价于 C++ 里的 projection[1][1] *= -1；确保只做一次
        proj[1, :] *= -1.0
    return proj

def make_viewproj_from_opencv(R, T, fx, fy, cx, cy, W, H, znear=0.01, zfar=100.0,
                              *, R_t_is_world_to_cam=True):
    view = opencv_extrinsics_to_view_vulkan(
        R, T, is_world_to_cam=R_t_is_world_to_cam, do_yz_flip=True
    )
    proj = opencv_intrinsics_to_proj_vulkan(
        fx, fy, cx, cy, W, H, znear, zfar, do_vulkan_y_flip=False
    )

    # ！！！与 glm::mat4(...) 的列主序构造对齐：按“列优先”展平发送
    view_flat = view.astype(np.float32).T.ravel()  # == Fortran 顺序
    proj_flat = proj.astype(np.float32).T.ravel()
    return view_flat, proj_flat



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
        
        for i in range(0, 10):  # Reduced to 5 frames for quicker testing
            # if (i ==1):
            #     t_all_start = perf_counter()
            # Create different camera positions for each frame
            distance = 4.0 + i * 0.5  # Move camera further away each frame
            yaw = i * 0.3  # Rotate around Y axis
            pitch = 0.0
            
            # view, proj = create_camera_matrices(distance, yaw, pitch)
      
            # R = np.array([[ 0.98822485,  0.11374114, -0.10234546],
            #             [-0.11979481,  0.99127023, -0.05506844],
            #             [ 0.09518846,  0.06668046,  0.99322348]], dtype=np.float32)
            # T = np.array([-2.80552141, -1.27673587,  5.06543639], dtype=np.float32)
      

            Fx = 1208.1880959114053
            Fy = 1209.669871748316
 
            W  = 1000
            H  = 1000
            Cx = W / 2
            Cy = H / 2
            znear, zfar = 0.001, 1000.0

            X = np.array([[1,0,0],
                        [0,0,1],
                        [0,1,0]], dtype=np.float32)

            
            # R = np.array([[ -1,  0, 0],
            #             [0, 0, 1],
            #             [ 0,  -1,  0]], dtype=np.float32)
            
            R = np.array([[ 1,  0, 0],
                        [0, 1, 0],
                        [ 0,  0, 1, ]], dtype=np.float32)

            # R   = X @ R 
            T = np.array([0,0,  10.], dtype=np.float32)

            # R = R.transpose(-2,-1)
            # 注意：COLMAP 的 (R, T) 通常是 world->cam
            view_flat, proj_flat = make_viewproj_from_opencv(
                R, T, Fx, Fy, Cx, Cy, W, H, znear, zfar, R_t_is_world_to_cam=True
            )

            print(f"Frame {i}: update_camera (frame_number={client.frame_number}, distance={distance:.1f})")
            client.update_camera(view_flat, proj_flat)
            print("✅ Camera matrices sent via socket")

            frame = client.get_frame(timeout_ms=2000)

            if frame is not None:
                client.save_frame_png(frame, f"success_test{i}.png")
                print(f"✅ Frame {i} saved")
            else:
                print(f"⚠️ Frame {i} capture failed")
            
        t_all = perf_counter() - t_all_start
        print(f"Total time for 600 frames: {t_all:.2f}s")
        time.sleep(10)
        if frame is not None:
            
            # print(frame.sum())
            print(f"✅ Got frame: {frame.shape if hasattr(frame, 'shape') else 'data received'}")
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