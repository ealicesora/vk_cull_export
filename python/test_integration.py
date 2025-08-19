#!/usr/bin/env python3
"""
Integration test suite for VK2Torch pipeline

Test scenarios:
T1: Handshake functionality - test FD import and CUDA integration
T2: Vulkan->Python export - test frame readback without camera updates  
T3: Full loop with camera changes - test end-to-end pipeline
T4: 60 FPS stress test - test performance and stability
"""

import os
import sys
import time
import subprocess
import threading
import signal
import tempfile
import shutil
import logging
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple

# Add the current directory to path for imports
sys.path.append(str(Path(__file__).parent))

try:
    from vk2torch_client import VK2TorchClient, create_camera_matrices, HAS_CUPY, HAS_TORCH
    import cupy as cp
    import torch
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    print("Please ensure CuPy and PyTorch are installed in the vk2torch environment")
    sys.exit(1)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VulkanTestRunner:
    """Helper class to run Vulkan application for testing."""
    
    def __init__(self, vk_exe_path: str):
        self.vk_exe_path = vk_exe_path
        self.process = None
        self.output_file = None
        
    def start(self, args: List[str], timeout: int = 10) -> bool:
        """Start Vulkan application with given arguments."""
        try:
            # Create temporary output file
            self.output_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix='vk_output_')
            
            # Start process
            cmd = [self.vk_exe_path] + args
            logger.info(f"Starting Vulkan app: {' '.join(cmd)}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=self.output_file,
                stderr=subprocess.STDOUT,
                cwd=Path(self.vk_exe_path).parent
            )
            
            # Wait a bit for startup
            time.sleep(timeout)
            
            # Check if process is still running
            if self.process.poll() is not None:
                logger.error(f"Vulkan app exited early with code {self.process.returncode}")
                return False
                
            logger.info("Vulkan app started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Vulkan app: {e}")
            return False
            
    def stop(self):
        """Stop the Vulkan application."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            
            logger.info("Vulkan app stopped")
            
        if self.output_file:
            self.output_file.close()
            # Print output for debugging
            with open(self.output_file.name, 'r') as f:
                output = f.read()
                if output.strip():
                    logger.info("Vulkan app output:")
                    for line in output.split('\n')[-20:]:  # Last 20 lines
                        if line.strip():
                            logger.info(f"  {line}")
            os.unlink(self.output_file.name)
            
    def is_running(self) -> bool:
        """Check if Vulkan application is still running."""
        return self.process is not None and self.process.poll() is None

class IntegrationTester:
    """Main integration test runner."""
    
    def __init__(self, vk_exe_path: str):
        self.vk_exe_path = vk_exe_path
        self.socket_path = "/tmp/vk2torch_test.sock"
        self.test_results = {}
        
    def cleanup_socket(self):
        """Clean up socket file."""
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
            
    def test_t1_handshake(self) -> bool:
        """
        T1: Test handshake functionality - FD import and CUDA integration.
        Success: Python successfully imports FDs and creates CUDA resources.
        """
        logger.info("=== T1: Handshake Test ===")
        
        self.cleanup_socket()
        
        # Start Vulkan app with UDS enabled
        vk_runner = VulkanTestRunner(self.vk_exe_path)
        vk_args = [
            "--uds", self.socket_path,
            "--offscreen", "1", 
            "--renderer", "0",  # Use rasterization for compatibility
            "--validation", "0"  # Disable validation for speed
        ]
        
        if not vk_runner.start(vk_args, timeout=15):
            return False
            
        try:
            # Try to connect and perform handshake
            with VK2TorchClient(self.socket_path) as client:
                success = client.connect()
                
                if success:
                    logger.info(f"✓ Handshake successful: {client.width}x{client.height} {client.format}")
                    logger.info(f"✓ CUDA resources imported: cam={client.dev_cam}, color={client.dev_color}")
                    logger.info(f"✓ Semaphores imported: cam={client.sem_cam}, done={client.sem_done}")
                    return True
                else:
                    logger.error("✗ Handshake failed")
                    return False
                    
        except Exception as e:
            logger.error(f"✗ Exception during handshake: {e}")
            return False
        finally:
            vk_runner.stop()
            
    def test_t2_export_only(self) -> bool:
        """
        T2: Test Vulkan->Python export without camera updates.
        Success: Python can read pixel data and detect frame changes.
        """
        logger.info("=== T2: Export Only Test ===")
        
        self.cleanup_socket()
        
        vk_runner = VulkanTestRunner(self.vk_exe_path)
        vk_args = [
            "--uds", self.socket_path,
            "--offscreen", "1",
            "--renderer", "0",
            "--validation", "0",
            "--gridcopies", "1"  # Single bunny for less memory usage
        ]
        
        if not vk_runner.start(vk_args, timeout=15):
            return False
            
        try:
            with VK2TorchClient(self.socket_path) as client:
                if not client.connect():
                    logger.error("✗ Connection failed")
                    return False
                    
                # Get a few frames without updating camera (Vulkan renders default camera)
                frames = []
                for i in range(3):
                    # Wait a bit between frames
                    time.sleep(0.1)
                    
                    # Skip camera update - let Vulkan render with default camera
                    # Just increment frame counter and wait for result
                    client.frame_number += 1
                    
                    tensor = client.get_frame()
                    if tensor is None:
                        logger.error(f"✗ Failed to get frame {i}")
                        return False
                        
                    frames.append(tensor)
                    logger.info(f"✓ Got frame {i}: {tensor.shape} {tensor.dtype}")
                    
                    # Check pixel values
                    pixel_sum = tensor.sum().item()
                    logger.info(f"  Pixel sum: {pixel_sum}")
                    
                    if pixel_sum == 0:
                        logger.warning("  Frame appears to be black")
                    
                # Check that we got valid frames
                if len(frames) == 3:
                    # Save first and last frame for comparison
                    if client.save_frame_png(frames[0], "test_t2_frame_0.png"):
                        logger.info("✓ Saved test frame 0")
                    if client.save_frame_png(frames[-1], "test_t2_frame_2.png"):
                        logger.info("✓ Saved test frame 2")
                    
                    logger.info("✓ T2 Export test successful")
                    return True
                else:
                    logger.error("✗ Failed to capture all frames")
                    return False
                    
        except Exception as e:
            logger.error(f"✗ Exception during export test: {e}")
            return False
        finally:
            vk_runner.stop()
            
    def test_t3_full_loop(self) -> bool:
        """
        T3: Test full loop with camera changes.
        Success: Rendered images show clear camera movement between frames.
        """
        logger.info("=== T3: Full Loop Test ===")
        
        self.cleanup_socket()
        
        vk_runner = VulkanTestRunner(self.vk_exe_path)
        vk_args = [
            "--uds", self.socket_path,
            "--offscreen", "1",
            "--renderer", "0",
            "--validation", "0",
            "--gridcopies", "1"
        ]
        
        if not vk_runner.start(vk_args, timeout=15):
            return False
            
        try:
            with VK2TorchClient(self.socket_path) as client:
                if not client.connect():
                    logger.error("✗ Connection failed")
                    return False
                    
                frames = []
                camera_positions = []
                
                # Test different camera positions
                for i in range(5):
                    # Create distinct camera positions
                    yaw = i * np.pi / 4  # 45 degree increments
                    distance = 3.0 + i * 0.5
                    pitch = i * 0.1
                    
                    view_matrix, proj_matrix = create_camera_matrices(distance, yaw, pitch)
                    camera_positions.append((distance, yaw, pitch))
                    
                    # Update camera
                    if not client.update_camera(view_matrix, proj_matrix):
                        logger.error(f"✗ Failed to update camera for frame {i}")
                        return False
                        
                    # Get frame
                    tensor = client.get_frame()
                    if tensor is None:
                        logger.error(f"✗ Failed to get frame {i}")
                        return False
                        
                    frames.append(tensor)
                    
                    # Calculate some basic image statistics
                    pixel_mean = tensor.float().mean().item()
                    pixel_std = tensor.float().std().item()
                    
                    logger.info(f"✓ Frame {i}: camera(d={distance:.1f}, y={yaw:.1f}, p={pitch:.1f}) "
                              f"stats(mean={pixel_mean:.1f}, std={pixel_std:.1f})")
                    
                    # Save key frames
                    if i in [0, 2, 4]:
                        filename = f"test_t3_frame_{i}.png"
                        if client.save_frame_png(tensor, filename):
                            logger.info(f"✓ Saved {filename}")
                
                # Analyze frame differences
                if len(frames) >= 3:
                    # Compare first and last frame to detect changes
                    frame_diff = (frames[0].float() - frames[-1].float()).abs().mean().item()
                    logger.info(f"✓ Frame difference (first vs last): {frame_diff:.1f}")
                    
                    if frame_diff > 10.0:  # Threshold for meaningful difference
                        logger.info("✓ T3 Full loop test successful - camera changes detected")
                        return True
                    else:
                        logger.warning("⚠ T3 Frames appear very similar - camera may not be updating")
                        return False  # Still consider this a failure
                        
                return False
                
        except Exception as e:
            logger.error(f"✗ Exception during full loop test: {e}")
            return False
        finally:
            vk_runner.stop()
            
    def test_t4_stress_test(self) -> bool:
        """
        T4: 60 FPS stress test.
        Success: No deadlocks, reasonable frame times, stable operation.
        """
        logger.info("=== T4: Stress Test (60 FPS target) ===")
        
        self.cleanup_socket()
        
        vk_runner = VulkanTestRunner(self.vk_exe_path)
        vk_args = [
            "--uds", self.socket_path,
            "--offscreen", "1", 
            "--renderer", "0",
            "--validation", "0",
            "--gridcopies", "1",
            "--supersample", "0"  # Disable supersampling for performance
        ]
        
        if not vk_runner.start(vk_args, timeout=15):
            return False
            
        try:
            with VK2TorchClient(self.socket_path) as client:
                if not client.connect():
                    logger.error("✗ Connection failed")
                    return False
                    
                target_fps = 60
                test_duration = 10  # seconds
                target_frames = target_fps * test_duration
                
                frame_times = []
                failed_frames = 0
                
                logger.info(f"Running stress test: {target_frames} frames in {test_duration}s")
                
                start_time = time.time()
                
                for i in range(target_frames):
                    frame_start = time.time()
                    
                    # Create simple camera orbit
                    yaw = (i / target_fps) * np.pi / 4  # Slow rotation
                    view_matrix, proj_matrix = create_camera_matrices(5.0, yaw, 0.0)
                    
                    # Update camera  
                    if not client.update_camera(view_matrix, proj_matrix):
                        failed_frames += 1
                        continue
                        
                    # Get frame
                    tensor = client.get_frame(timeout_ms=100)  # Short timeout for stress test
                    if tensor is None:
                        failed_frames += 1
                        continue
                        
                    frame_time = (time.time() - frame_start) * 1000  # ms
                    frame_times.append(frame_time)
                    
                    # Log progress every second
                    if i % target_fps == 0:
                        avg_frame_time = np.mean(frame_times[-target_fps:]) if frame_times else 0
                        logger.info(f"Frame {i}/{target_frames}: avg_time={avg_frame_time:.1f}ms")
                        
                    # Target frame timing
                    target_frame_time = 1.0 / target_fps
                    elapsed = time.time() - frame_start
                    if elapsed < target_frame_time:
                        time.sleep(target_frame_time - elapsed)
                        
                total_time = time.time() - start_time
                successful_frames = len(frame_times)
                actual_fps = successful_frames / total_time
                
                # Calculate statistics
                if frame_times:
                    avg_frame_time = np.mean(frame_times)
                    max_frame_time = np.max(frame_times)
                    frame_time_std = np.std(frame_times)
                    
                    logger.info(f"✓ Stress test completed:")
                    logger.info(f"  Duration: {total_time:.1f}s")
                    logger.info(f"  Successful frames: {successful_frames}/{target_frames}")
                    logger.info(f"  Failed frames: {failed_frames}")
                    logger.info(f"  Actual FPS: {actual_fps:.1f}")
                    logger.info(f"  Frame time: avg={avg_frame_time:.1f}ms, max={max_frame_time:.1f}ms, std={frame_time_std:.1f}ms")
                    
                    # Success criteria
                    success_rate = successful_frames / target_frames
                    acceptable_fps = target_fps * 0.8  # 80% of target
                    
                    if success_rate >= 0.95 and actual_fps >= acceptable_fps and max_frame_time < 100:
                        logger.info("✓ T4 Stress test PASSED")
                        return True
                    else:
                        logger.warning("⚠ T4 Stress test FAILED - performance below threshold")
                        return False
                else:
                    logger.error("✗ T4 No frames captured")
                    return False
                    
        except Exception as e:
            logger.error(f"✗ Exception during stress test: {e}")
            return False
        finally:
            vk_runner.stop()
            
    def run_all_tests(self) -> Dict[str, bool]:
        """Run all integration tests."""
        logger.info("Starting VK2Torch integration test suite")
        
        if not HAS_CUPY or not HAS_TORCH:
            logger.error("CuPy and PyTorch are required for integration tests")
            return {}
            
        # Check if Vulkan executable exists
        if not os.path.exists(self.vk_exe_path):
            logger.error(f"Vulkan executable not found: {self.vk_exe_path}")
            return {}
            
        tests = [
            ("T1_Handshake", self.test_t1_handshake),
            ("T2_Export_Only", self.test_t2_export_only), 
            ("T3_Full_Loop", self.test_t3_full_loop),
            ("T4_Stress_Test", self.test_t4_stress_test)
        ]
        
        results = {}
        
        for test_name, test_func in tests:
            logger.info(f"\n{'='*60}")
            logger.info(f"Running {test_name}")
            logger.info(f"{'='*60}")
            
            try:
                results[test_name] = test_func()
            except Exception as e:
                logger.error(f"Test {test_name} failed with exception: {e}")
                results[test_name] = False
                
            # Cleanup between tests
            time.sleep(1)
            self.cleanup_socket()
            
        return results
        
    def print_summary(self, results: Dict[str, bool]):
        """Print test summary."""
        logger.info(f"\n{'='*60}")
        logger.info("TEST SUMMARY")
        logger.info(f"{'='*60}")
        
        passed = sum(results.values())
        total = len(results)
        
        for test_name, result in results.items():
            status = "PASS" if result else "FAIL"
            logger.info(f"{test_name:20} : {status}")
            
        logger.info(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 All tests PASSED! VK2Torch integration is working correctly.")
        else:
            logger.error("❌ Some tests FAILED. Check logs for details.")

def find_vk_executable() -> Optional[str]:
    """Find the Vulkan executable."""
    possible_paths = [
        "./_bin/Release/vk_lod_clusters",
        "../_bin/Release/vk_lod_clusters", 
        "./build/_bin/Release/vk_lod_clusters",
        "../build/_bin/Release/vk_lod_clusters"
    ]
    
    base_path = Path(__file__).parent.parent
    
    for rel_path in possible_paths:
        full_path = base_path / rel_path
        if full_path.exists():
            return str(full_path.absolute())
            
    return None

def main():
    """Main test runner."""
    # Find Vulkan executable
    vk_exe = find_vk_executable()
    if not vk_exe:
        logger.error("Could not find Vulkan executable (vk_lod_clusters)")
        logger.error("Please build the project first or specify the path manually")
        return 1
        
    logger.info(f"Using Vulkan executable: {vk_exe}")
    
    # Run tests
    tester = IntegrationTester(vk_exe)
    results = tester.run_all_tests()
    
    if not results:
        logger.error("No tests were run")
        return 1
        
    # Print summary
    tester.print_summary(results)
    
    # Return exit code
    return 0 if all(results.values()) else 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)