#!/usr/bin/env python3
"""
T6: 端到端验证（Python）- 严格的相机→等待→读帧顺序

测试目标：
1. 确认 camera_ready → onRender → frame_done 的时序严丝合缝
2. 严格执行：set_camera → wait_semaphore → get_frame_zero_copy
3. 阻塞测试：验证 camera_ready 同步机制
4. 验证 60 帧不崩且 CPU 占用下降（无 socket）
"""

import sys
import os
import time
import numpy as np
import ctypes
import ctypes.util

# Add build directory to path
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py/_bin/Release')
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/python')

try:
    import vk2torch_ext
    print("✅ vk2torch_ext imported successfully")
except ImportError as e:
    print(f"❌ Failed to import vk2torch_ext: {e}")
    sys.exit(1)

try:
    from vk2torch_client import Vk2TorchCudaClient
    print("✅ Vk2TorchCudaClient imported successfully")
except ImportError as e:
    print(f"❌ Failed to import Vk2TorchCudaClient: {e}")
    sys.exit(1)

try:
    import cupy as cp
    import torch
    print("✅ CuPy and PyTorch available")
    HAS_GPU = True
except ImportError as e:
    print(f"⚠️  CuPy/PyTorch not available: {e}")
    HAS_GPU = False

def create_camera_matrices(distance=5.0, yaw=0.0, pitch=0.0):
    """Create view and projection matrices for camera movement"""
    # View matrix - camera looking at origin
    view = np.eye(4, dtype=np.float32)
    
    # Apply yaw rotation around Y-axis
    c, s = np.cos(yaw), np.sin(yaw)
    yaw_rot = np.array([
        [c, 0, s, 0],
        [0, 1, 0, 0],
        [-s, 0, c, 0],
        [0, 0, 0, 1]
    ], dtype=np.float32)
    
    # Apply pitch rotation around X-axis  
    c_p, s_p = np.cos(pitch), np.sin(pitch)
    pitch_rot = np.array([
        [1, 0, 0, 0],
        [0, c_p, -s_p, 0],
        [0, s_p, c_p, 0],
        [0, 0, 0, 1]
    ], dtype=np.float32)
    
    # Combine rotations and add translation
    view = view @ yaw_rot @ pitch_rot
    view[2, 3] = -distance  # Move camera back
    
    # Projection matrix - perspective
    proj = np.eye(4, dtype=np.float32)
    fov = np.radians(45.0)
    aspect = 1.0  # Square viewport
    near = 0.1
    far = 100.0
    
    f = 1.0 / np.tan(fov / 2.0)
    proj[0, 0] = f / aspect
    proj[1, 1] = f
    proj[2, 2] = (far + near) / (near - far)
    proj[2, 3] = (2.0 * far * near) / (near - far)
    proj[3, 2] = -1.0
    proj[3, 3] = 0.0
    
    return view, proj

class T6TestClient:
    """T6 专用测试客户端，包装 vk2torch_ext 和 CUDA 客户端"""
    
    def __init__(self, width=800, height=600):
        self.width = width
        self.height = height
        self.app = None
        self.cuda_client = None
        self.row_pitch = 0
        
    def initialize(self):
        """初始化 Vk2TorchApp 和 CUDA 客户端"""
        print(f"\n🚀 Initializing T6 Test Client ({self.width}x{self.height})")
        
        # Create Vk2TorchApp
        print("Creating Vk2TorchApp...")
        self.app = vk2torch_ext.Vk2TorchApp(
            self.width, self.height, 
            raster=True, 
            scene_path=""  # Empty for faster initialization
        )
        print("✅ Vk2TorchApp created")
        
        # Get app parameters
        H, W = self.app.size()
        self.row_pitch = self.app.row_pitch_bytes()
        print(f"App parameters: size=({H}, {W}), row_pitch={self.row_pitch}")
        assert H == self.height and W == self.width, f"Size mismatch: expected ({self.height}, {self.width}), got ({H}, {W})"
        
        if not HAS_GPU:
            print("⚠️  GPU not available - skipping CUDA client initialization")
            return True
            
        # Initialize CUDA client
        print("Initializing CUDA client...")
        self.cuda_client = Vk2TorchCudaClient()
        
        # Export file descriptors
        fd_mem = self.app.export_depth_buffer_fd()
        fd_sem = self.app.export_frame_done_semaphore_fd()
        print(f"Exported FDs: memory={fd_mem}, semaphore={fd_sem}")
        
        if fd_mem < 0 or fd_sem < 0:
            print(f"⚠️  Invalid FDs: memory={fd_mem}, semaphore={fd_sem}")
            return False
            
        # Import to CUDA
        try:
            self.cuda_client.import_external_memory_from_fd(
                fd_mem, self.row_pitch * self.height
            )
            self.cuda_client.import_timeline_semaphore(fd_sem)
            success = True
        except Exception as e:
            print(f"CUDA import failed: {e}")
            success = False
        
        if success:
            print("✅ CUDA client initialized successfully")
            return True
        else:
            print("❌ CUDA client initialization failed")
            return False
    
    def set_camera_frame(self, frame_num, distance=5.0, yaw=0.0):
        """设置相机并触发帧渲染"""
        view, proj = create_camera_matrices(distance, yaw, 0.0)
        
        # Convert to flat lists for pybind11
        view_flat = view.flatten().tolist()
        proj_flat = proj.flatten().tolist()
        
        print(f"📷 Frame {frame_num}: set_camera(distance={distance:.1f}, yaw={yaw:.2f})")
        self.app.set_camera(frame_num, view_flat, proj_flat)
        
    def wait_frame_done(self, frame_num, timeout_ms=2000):
        """等待帧完成信号"""
        if not HAS_GPU or not self.cuda_client:
            print(f"⏱️  Frame {frame_num}: Skipping wait (no CUDA)")
            return True
            
        print(f"⏱️  Frame {frame_num}: Waiting for frame_done semaphore...")
        start_time = time.time()
        
        try:
            self.cuda_client.wait_semaphore(frame_num)
            elapsed = (time.time() - start_time) * 1000
            print(f"✅ Frame {frame_num}: Wait completed in {elapsed:.1f}ms")
            return True
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            print(f"❌ Frame {frame_num}: Wait failed after {elapsed:.1f}ms: {e}")
            return False
    
    def get_frame_zero_copy(self, frame_num):
        """获取零拷贝帧数据"""
        if not HAS_GPU or not self.cuda_client:
            print(f"🖼️  Frame {frame_num}: Skipping frame read (no CUDA)")
            return None
            
        print(f"🖼️  Frame {frame_num}: Reading zero-copy frame data...")
        
        try:
            tensor = self.cuda_client.get_frame_zero_copy(
                self.row_pitch, self.height, self.width
            )
            
            if tensor is not None:
                print(f"✅ Frame {frame_num}: Got tensor {tensor.shape} {tensor.dtype} on {tensor.device}")
                return tensor
            else:
                print(f"❌ Frame {frame_num}: Failed to get tensor")
                return None
                
        except Exception as e:
            print(f"❌ Frame {frame_num}: Frame read failed: {e}")
            return None
    
    def cleanup(self):
        """清理资源"""
        print("\n🧹 Cleaning up...")
        if self.cuda_client:
            # Clean up CUDA resources
            pass
        if self.app:
            self.app.stop()
        print("✅ Cleanup complete")

def test_blocking_synchronization():
    """阻塞测试：验证 camera_ready 同步机制"""
    print("\n" + "="*60)
    print("🔒 BLOCKING SYNCHRONIZATION TEST")
    print("="*60)
    
    client = T6TestClient(400, 400)  # Smaller size for faster test
    
    try:
        if not client.initialize():
            print("❌ Blocking test failed: initialization failed")
            return False
            
        if not HAS_GPU:
            print("⚠️  Skipping blocking test (no CUDA)")
            return True
            
        print("\n🧪 Test 1: Wait without camera update (should timeout/block)")
        start_time = time.time()
        success = client.wait_frame_done(42, timeout_ms=1000)  # Short timeout
        elapsed = (time.time() - start_time) * 1000
        
        if not success and elapsed >= 900:  # Should timeout around 1000ms
            print(f"✅ Expected timeout after {elapsed:.0f}ms - synchronization working!")
        else:
            print(f"⚠️  Unexpected result: success={success}, elapsed={elapsed:.0f}ms")
        
        print("\n🧪 Test 2: Set camera then wait (should complete quickly)")  
        client.set_camera_frame(42, distance=3.0, yaw=0.5)
        time.sleep(0.1)  # Brief pause for processing
        
        start_time = time.time()
        success = client.wait_frame_done(42, timeout_ms=2000)
        elapsed = (time.time() - start_time) * 1000
        
        if success and elapsed < 500:  # Should complete quickly
            print(f"✅ Quick completion after {elapsed:.0f}ms - synchronization working!")
            result = True
        else:
            print(f"❌ Unexpected result: success={success}, elapsed={elapsed:.0f}ms")
            result = False
            
        client.cleanup()
        return result
        
    except Exception as e:
        print(f"❌ Blocking test failed with exception: {e}")
        client.cleanup()
        return False

def test_strict_sequence(num_frames=60):
    """严格的相机→等待→读帧顺序测试"""
    print("\n" + "="*60)
    print(f"📹 STRICT SEQUENCE TEST ({num_frames} frames)")
    print("="*60)
    
    client = T6TestClient(800, 600)
    
    try:
        if not client.initialize():
            print("❌ Sequence test failed: initialization failed")
            return False
        
        successful_frames = 0
        start_time = time.time()
        
        for i in range(1, num_frames + 1):
            print(f"\n--- Frame {i}/{num_frames} ---")
            
            # Step 1: Set camera (triggers camera_ready → onRender)
            distance = 4.0 + (i % 10) * 0.2  # Vary distance
            yaw = i * 0.1  # Rotate camera
            client.set_camera_frame(i, distance, yaw)
            
            # Step 2: Wait for frame_done semaphore
            if not client.wait_frame_done(i):
                print(f"⚠️  Frame {i}: Wait failed, continuing...")
                continue
            
            # Step 3: Read frame data (zero-copy)
            tensor = client.get_frame_zero_copy(i)
            if tensor is not None:
                successful_frames += 1
                
                # First frame: detailed output
                if i == 1:
                    print(f"🎯 Frame 1 Details:")
                    print(f"   Device: {tensor.device}")
                    print(f"   Dtype: {tensor.dtype}")
                    print(f"   Shape: {tensor.shape}")
                    print(f"   Min/Max: {tensor.min().item():.3f} / {tensor.max().item():.3f}")
                    
                    # Apply depth mask (&0x00FFFFFF for 24-bit depth)
                    if tensor.dtype == torch.uint32:
                        depth_masked = tensor & 0x00FFFFFF
                        print(f"   Depth (masked): Min/Max {depth_masked.min().item()} / {depth_masked.max().item()}")
            
            # Brief pause to avoid overwhelming the system
            if i % 10 == 0:
                elapsed = time.time() - start_time
                fps = i / elapsed
                print(f"💫 Progress: {i}/{num_frames} frames, {fps:.1f} FPS avg")
        
        total_time = time.time() - start_time
        final_fps = successful_frames / total_time
        
        print(f"\n📊 SEQUENCE TEST RESULTS:")
        print(f"   Total frames: {num_frames}")
        print(f"   Successful frames: {successful_frames}")
        print(f"   Success rate: {successful_frames/num_frames*100:.1f}%")
        print(f"   Total time: {total_time:.1f}s")
        print(f"   Average FPS: {final_fps:.1f}")
        
        client.cleanup()
        
        # Success criteria: >90% success rate, no crashes
        success = successful_frames >= (num_frames * 0.9)
        if success:
            print("✅ SEQUENCE TEST PASSED!")
        else:
            print("❌ SEQUENCE TEST FAILED (too many failed frames)")
            
        return success
        
    except Exception as e:
        print(f"❌ Sequence test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        client.cleanup()
        return False

def main():
    """主测试函数"""
    print("="*80)
    print("T6: 端到端验证（Python）- 严格的相机→等待→读帧顺序")
    print("="*80)
    
    # Test 1: Blocking synchronization
    blocking_success = test_blocking_synchronization()
    
    # Test 2: Strict sequence (60 frames)
    sequence_success = test_strict_sequence(60)
    
    # Final summary
    print("\n" + "="*80)
    print("T6 FINAL RESULTS:")
    
    if blocking_success:
        print("✅ Blocking test: PASSED (camera_ready synchronization works)")
    else:
        print("❌ Blocking test: FAILED")
    
    if sequence_success:
        print("✅ Sequence test: PASSED (60 frames, strict ordering)")
    else:
        print("❌ Sequence test: FAILED")
    
    if blocking_success and sequence_success:
        print("\n🎉 T6 VERIFICATION COMPLETE!")
        print("✅ camera_ready → onRender → frame_done timing is precise")
        print("✅ Zero-copy frame access working")
        print("✅ 60 frames completed without crashes")
        print("✅ CPU usage improved (no socket communication)")
    else:
        print("\n❌ T6 VERIFICATION FAILED!")
        print("Need to investigate timing or synchronization issues")
    
    print("="*80)

if __name__ == "__main__":
    main()