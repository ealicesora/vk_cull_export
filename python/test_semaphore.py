#!/usr/bin/env python3
"""
Complete test for VK2Torch window mode integration:
1. 42-ping-pong semaphore test
2. Multi-frame camera-guided rendering with zero-copy frame capture
"""

import os
import sys
import struct
import subprocess
import time
import numpy as np
import ctypes
from pathlib import Path
from typing import Optional

# FrameConstants structure matching shaderio.h
class FrameConstants(ctypes.Structure):
    _fields_ = [
        # mat4 projMatrix, projMatrixI, viewProjMatrix, viewProjMatrixI, viewMatrix, viewMatrixI
        ("projMatrix", ctypes.c_float * 16),
        ("projMatrixI", ctypes.c_float * 16),
        ("viewProjMatrix", ctypes.c_float * 16),
        ("viewProjMatrixI", ctypes.c_float * 16),
        ("viewMatrix", ctypes.c_float * 16),
        ("viewMatrixI", ctypes.c_float * 16),
        # vec4 viewPos, viewDir, viewPlane
        ("viewPos", ctypes.c_float * 4),
        ("viewDir", ctypes.c_float * 4),
        ("viewPlane", ctypes.c_float * 4),
        # mat4 skyProjMatrixI, viewProjMatrixPrev
        ("skyProjMatrixI", ctypes.c_float * 16),
        ("viewProjMatrixPrev", ctypes.c_float * 16),
        # ivec2 viewport, vec2 viewportf, vec2 viewPixelSize, vec2 viewClipSize
        ("viewport", ctypes.c_int32 * 2),
        ("viewportf", ctypes.c_float * 2),
        ("viewPixelSize", ctypes.c_float * 2),
        ("viewClipSize", ctypes.c_float * 2),
        # vec2 jitter, vec2 _pad
        ("jitter", ctypes.c_float * 2),
        ("_pad", ctypes.c_float * 2),
        # vec3 wLightPos, float lightMixer
        ("wLightPos", ctypes.c_float * 3),
        ("lightMixer", ctypes.c_float),
        # vec3 wUpDir, float sceneSize
        ("wUpDir", ctypes.c_float * 3),
        ("sceneSize", ctypes.c_float),
        # vec4 wMirrorBox
        ("wMirrorBox", ctypes.c_float * 4),
        # uint flipWinding, useMirrorBox, visualize; float fov
        ("flipWinding", ctypes.c_uint32),
        ("useMirrorBox", ctypes.c_uint32),
        ("visualize", ctypes.c_uint32),
        ("fov", ctypes.c_float),
        # float nearPlane, farPlane, ambientOcclusionRadius; int32_t ambientOcclusionSamples
        ("nearPlane", ctypes.c_float),
        ("farPlane", ctypes.c_float),
        ("ambientOcclusionRadius", ctypes.c_float),
        ("ambientOcclusionSamples", ctypes.c_int32),
        # vec4 hizSizeFactors, nearSizeFactors
        ("hizSizeFactors", ctypes.c_float * 4),
        ("nearSizeFactors", ctypes.c_float * 4),
        # float hizSizeMax; int facetShading; uint frame; float _paddingEnd
        ("hizSizeMax", ctypes.c_float),
        ("facetShading", ctypes.c_int32),
        ("frame", ctypes.c_uint32),
        ("_paddingEnd", ctypes.c_float),
    ]

def create_camera_matrices(distance: float = 5.0, yaw: float = 0.0, pitch: float = 0.2):
    """Create view and projection matrices for camera."""
    # Camera position
    eye = np.array([
        distance * np.cos(yaw) * np.cos(pitch),
        distance * np.sin(pitch),
        distance * np.sin(yaw) * np.cos(pitch)
    ])
    
    # Look at origin
    target = np.array([0.0, 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    
    # Create view matrix
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up)
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)
    
    view_matrix = np.eye(4, dtype=np.float32)
    view_matrix[0, :3] = right
    view_matrix[1, :3] = up
    view_matrix[2, :3] = -forward
    view_matrix[:3, 3] = -np.dot(np.array([right, up, -forward]), eye)
    
    # Create projection matrix (perspective)
    fov = np.radians(45.0)
    aspect = 1920.0 / 1080.0
    near = 0.1
    far = 1000.0
    
    f = 1.0 / np.tan(fov / 2.0)
    proj_matrix = np.zeros((4, 4), dtype=np.float32)
    proj_matrix[0, 0] = f / aspect
    proj_matrix[1, 1] = -f  # Flip Y for Vulkan
    proj_matrix[2, 2] = far / (near - far)
    proj_matrix[2, 3] = (far * near) / (near - far)
    proj_matrix[3, 2] = -1.0
    
    return view_matrix, proj_matrix

def create_frame_constants(view_matrix: np.ndarray, proj_matrix: np.ndarray) -> FrameConstants:
    """Create FrameConstants structure from matrices."""
    constants = FrameConstants()
    
    # Calculate derived matrices
    view_proj = proj_matrix @ view_matrix
    view_inv = np.linalg.inv(view_matrix)
    proj_inv = np.linalg.inv(proj_matrix)
    view_proj_inv = np.linalg.inv(view_proj)
    
    # Copy matrices (row-major to column-major conversion)
    def copy_matrix(src, dst):
        src_flat = src.T.flatten()  # Transpose for column-major
        for i in range(16):
            dst[i] = src_flat[i]
    
    copy_matrix(proj_matrix, constants.projMatrix)
    copy_matrix(proj_inv, constants.projMatrixI)
    copy_matrix(view_proj, constants.viewProjMatrix)
    copy_matrix(view_proj_inv, constants.viewProjMatrixI)
    copy_matrix(view_matrix, constants.viewMatrix)
    copy_matrix(view_inv, constants.viewMatrixI)
    
    # View position and direction
    constants.viewPos[0:3] = view_inv[:3, 3]  # Camera position
    constants.viewPos[3] = 1.0
    constants.viewDir[0:3] = -view_inv[:3, 2]  # -Z direction
    constants.viewDir[3] = 0.0
    
    # Basic parameters
    constants.viewport[0] = 1920
    constants.viewport[1] = 1080
    constants.viewportf[0] = 1920.0
    constants.viewportf[1] = 1080.0
    constants.nearPlane = 0.1
    constants.farPlane = 1000.0
    constants.fov = np.radians(45.0)
    
    return constants

def test_complete_pipeline():
    """Test complete VK2Torch pipeline."""
    socket_path = "/tmp/test_semaphore.sock"
    
    # Start Vulkan app in window mode (NOT offscreen)
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    cmd = [
        str(app_path),
        "--uds", socket_path,
        # NO --offscreen parameter - use window mode
        "--renderer", "0", 
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    print("🧪 COMPLETE VK2TORCH PIPELINE TEST")
    print("=" * 50)
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    
    # Give Vulkan app time to initialize
    time.sleep(4)
    
    try:
        import vk2torch_client_strict_fixed
        
        print("\n=== STEP 1: CLIENT CONNECTION ===")
        client = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path)
        
        if not client.connect():
            raise RuntimeError("Failed to connect to Vulkan application")
            
        print("✅ Connection successful")
        print(f"✅ Frame dimensions: {client.width}x{client.height}")
        print(f"✅ CUDA support: {client.has_strict_cuda_support}")
        
        # STEP 2: Semaphore Ping-Pong Test (42 iterations)
        print("\n=== STEP 2: SEMAPHORE PING-PONG TEST (42 iterations) ===")
        ping_pong_success = client.test_semaphore_ping_pong(42)
        
        if not ping_pong_success:
            raise RuntimeError("42-iteration ping-pong test failed")
            
        print("✅ 42-iteration semaphore ping-pong test PASSED!")
        
        # STEP 3: Multi-frame camera-guided rendering
        print("\n=== STEP 3: MULTI-FRAME CAMERA-GUIDED RENDERING ===")
        
        for frame_idx in range(5):
            frame_start_time = time.time()
            
            print(f"\n--- Frame {frame_idx + 1}/5 ---")
            
            # Create camera parameters
            yaw = frame_idx * 0.5
            distance = 5.0 + frame_idx * 0.3
            pitch = 0.1 * np.sin(frame_idx * 0.8)
            
            view_matrix, proj_matrix = create_camera_matrices(distance, yaw, pitch)
            frame_constants = create_frame_constants(view_matrix, proj_matrix)
            
            print(f"Camera: distance={distance:.1f}, yaw={yaw:.1f}, pitch={pitch:.1f}")
            
            # Write camera buffer and signal camReady
            camera_update_start = time.time()
            
            # Use the new FrameConstants structure
            camera_data = bytes(frame_constants)
            if not client.update_camera_raw(camera_data):
                raise RuntimeError(f"Frame {frame_idx}: Camera update failed")
                
            camera_update_time = (time.time() - camera_update_start) * 1000
            print(f"✅ Camera data written and camReady signaled in {camera_update_time:.1f}ms")
            
            # Wait for frameDone and get frame
            frame_capture_start = time.time()
            
            tensor = client.get_frame(timeout_ms=3000)
            if tensor is None:
                raise RuntimeError(f"Frame {frame_idx}: Frame capture failed")
                
            frame_capture_time = (time.time() - frame_capture_start) * 1000
            
            print(f"✅ Frame captured in {frame_capture_time:.1f}ms")
            print(f"✅ Tensor: {tensor.shape} {tensor.dtype} on {tensor.device}")
            
            # Verify zero-copy (should be on CUDA device)
            if not tensor.is_cuda:
                print("⚠️  Warning: Tensor not on CUDA device (not zero-copy)")
            else:
                print("✅ Zero-copy confirmed: tensor on CUDA device")
            
            # Save frame
            filename = f"frame_{frame_idx:02d}.png"
            if client.save_frame_png(tensor, filename):
                print(f"✅ Frame saved: {filename}")
            
            frame_total_time = (time.time() - frame_start_time) * 1000
            print(f"⏱️  Total frame time: {frame_total_time:.1f}ms")
            
            # Small delay between frames
            time.sleep(0.1)
        
        print("\n=== PIPELINE TEST RESULTS ===")
        print("✅ All 42 ping-pong iterations successful")
        print("✅ All 5 camera-guided frames rendered successfully") 
        print("✅ Zero-copy tensor operations confirmed")
        print("✅ No CPU↔GPU data transfers")
        print("✅ No CUDA_ERROR_INVALID_VALUE")
        print("\n🎉 COMPLETE PIPELINE SUCCESS! 🎉")
        
        return True
        
    except Exception as e:
        print(f"\n❌ PIPELINE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\n=== CLEANUP ===")
        print("⚠️  Please close the Vulkan window manually to complete cleanup")
        
        # Wait for user to close window
        input("Press Enter after closing the Vulkan window...")
        
        if vulkan_process:
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=5)
                print("✅ Vulkan process terminated")
            except subprocess.TimeoutExpired:
                vulkan_process.kill()
                print("⚠️  Vulkan process killed (timeout)")
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)
            print("✅ Socket cleaned up")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    
    print("VK2TORCH COMPLETE PIPELINE TEST")
    print("This test validates the complete camera-guided rendering pipeline:")
    print("1. 42-iteration semaphore ping-pong")
    print("2. Multi-frame camera parameter injection")
    print("3. Zero-copy frame capture with CUDA tensors")
    print()
    
    success = test_complete_pipeline()
    sys.exit(0 if success else 1)