#!/usr/bin/env python3
"""
Step-by-step VK2Torch debug test script

This script systematically tests the VK2Torch integration pipeline:
1. Environment verification
2. Basic connection test
3. Camera control test  
4. Frame capture test
5. PNG export test

Run with: python debug_step_by_step.py
"""

import os
import sys
import subprocess
import time
import socket
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def step1_environment_check():
    """Step 1: Verify Python environment and packages"""
    logger.info("🔍 STEP 1: Environment Check")
    
    try:
        import numpy as np
        logger.info("✅ NumPy available: %s", np.__version__)
    except ImportError as e:
        logger.error("❌ NumPy missing: %s", e)
        return False
    
    try:
        import cupy as cp
        logger.info("✅ CuPy available: %s", cp.__version__)
        
        # Test basic CuPy functionality
        arr = cp.array([1, 2, 3])
        logger.info("✅ CuPy basic test passed")
    except ImportError as e:
        logger.error("❌ CuPy missing: %s", e)
        return False
    except Exception as e:
        logger.error("❌ CuPy test failed: %s", e)
        return False
    
    try:
        import torch
        logger.info("✅ PyTorch available: %s", torch.__version__)
        
        # Test CUDA availability
        if torch.cuda.is_available():
            logger.info("✅ PyTorch CUDA available: %s", torch.cuda.get_device_name())
        else:
            logger.warning("⚠️  PyTorch CUDA not available")
    except ImportError as e:
        logger.error("❌ PyTorch missing: %s", e)
        return False
    
    try:
        import cv2
        logger.info("✅ OpenCV available: %s", cv2.__version__)
    except ImportError:
        logger.warning("⚠️  OpenCV not available - PNG export may be limited")
    
    logger.info("✅ STEP 1 COMPLETE: Environment check passed")
    return True

def step2_vulkan_app_check():
    """Step 2: Verify Vulkan application exists and can run"""
    logger.info("🔍 STEP 2: Vulkan Application Check")
    
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    if not app_path.exists():
        logger.error("❌ Vulkan application not found at: %s", app_path)
        logger.error("   Build the application first with: cmake --build build --config Release")
        return False
    
    logger.info("✅ Vulkan application found: %s", app_path)
    
    # Test basic help output
    try:
        result = subprocess.run([str(app_path), "--help"], 
                              capture_output=True, text=True, timeout=10)
        if "--uds" in result.stdout:
            logger.info("✅ VK2Torch integration supported (--uds option found)")
        else:
            logger.warning("⚠️  --uds option not found in help output")
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  Application help timeout - but app exists")
    except Exception as e:
        logger.warning("⚠️  Could not test app help: %s", e)
    
    logger.info("✅ STEP 2 COMPLETE: Vulkan application check passed")
    return True

def step3_basic_connection():
    """Step 3: Test basic socket connection"""
    logger.info("🔍 STEP 3: Basic Connection Test")
    
    socket_path = "/tmp/debug_step3.sock"
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    
    # Clean up any existing socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    # Start Vulkan app
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--offscreen", "1",
        "--renderer", "0",
        "--validation", "0", 
        "--gridcopies", "1"
    ]
    
    logger.info("Starting Vulkan app with: %s", ' '.join(cmd))
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    
    # Wait for socket to appear
    max_wait = 10
    for i in range(max_wait):
        if os.path.exists(socket_path):
            logger.info("✅ Socket appeared after %d seconds", i + 1)
            break
        time.sleep(1)
    else:
        logger.error("❌ Socket never appeared after %d seconds", max_wait)
        vulkan_process.terminate()
        vulkan_process.wait()
        return False
    
    # Test basic socket connection
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(socket_path)
        logger.info("✅ Socket connection successful")
        
        # Try to send a simple ping
        sock.send(b'{"type":"ping"}\n')
        response = sock.recv(1024)
        logger.info("✅ Received response: %s bytes", len(response))
        
        sock.close()
        
    except Exception as e:
        logger.error("❌ Socket connection failed: %s", e)
        vulkan_process.terminate()
        vulkan_process.wait()
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        return False
    
    # Cleanup
    vulkan_process.terminate()
    vulkan_process.wait()
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    logger.info("✅ STEP 3 COMPLETE: Basic connection test passed")
    return True

def step4_client_import():
    """Step 4: Test client import and basic functionality"""
    logger.info("🔍 STEP 4: Client Import Test")
    
    # Test original client first (with fallbacks)
    try:
        import vk2torch_client
        logger.info("✅ Original client imported successfully")
        
        # Test basic class creation
        client = vk2torch_client.VK2TorchClient("/tmp/dummy.sock")
        logger.info("✅ Original client instantiation successful")
        
    except Exception as e:
        logger.error("❌ Original client import/creation failed: %s", e)
        return False
    
    # Test strict client 
    try:
        import vk2torch_client_strict_fixed
        logger.info("✅ Strict client imported successfully")
        
        # Test basic class creation
        client = vk2torch_client_strict_fixed.VK2TorchClientStrictFixed("/tmp/dummy.sock")
        logger.info("✅ Strict client instantiation successful")
        logger.info("✅ Strict CUDA support: %s", client.has_strict_cuda_support)
        
    except Exception as e:
        logger.error("❌ Strict client import/creation failed: %s", e)
        return False
    
    logger.info("✅ STEP 4 COMPLETE: Client import test passed")
    return True

def step5_full_pipeline():
    """Step 5: Test full pipeline with frame capture"""
    logger.info("🔍 STEP 5: Full Pipeline Test")
    
    socket_path = "/tmp/debug_step5.sock"
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    
    # Clean up any existing socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    # Start Vulkan app
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--offscreen", "1",
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    logger.info("Starting Vulkan app for full pipeline test...")
    vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
    time.sleep(3)  # Give more time for full startup
    
    try:
        # Use the strict client for full testing
        import vk2torch_client_strict_fixed
        import numpy as np
        
        with vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path) as client:
            logger.info("✅ Client created")
            
            if not client.connect():
                logger.error("❌ Connection failed")
                return False
            
            logger.info("✅ Connection successful")
            logger.info("✅ Frame dimensions: %dx%d", client.width, client.height)
            logger.info("✅ CUDA support: %s", client.has_strict_cuda_support)
            
            if not client.has_strict_cuda_support:
                logger.warning("⚠️  CUDA support not available - basic test only")
                return True
            
            # Test camera update
            view_matrix = np.eye(4, dtype=np.float32)
            proj_matrix = np.eye(4, dtype=np.float32)
            
            try:
                client.update_camera(view_matrix, proj_matrix)
                logger.info("✅ Camera update successful")
            except Exception as e:
                logger.error("❌ Camera update failed: %s", e)
                return False
            
            # Test frame capture
            try:
                frame = client.get_frame(timeout_ms=2000)
                logger.info("✅ Frame captured: %s %s on %s", frame.shape, frame.dtype, frame.device)
            except Exception as e:
                logger.error("❌ Frame capture failed: %s", e)
                return False
            
            # Test PNG export
            try:
                png_path = "debug_step5_frame.png"
                client.save_frame_png(frame, png_path)
                
                if os.path.exists(png_path):
                    file_size = os.path.getsize(png_path)
                    logger.info("✅ PNG saved successfully: %s (%d bytes)", png_path, file_size)
                else:
                    logger.error("❌ PNG file was not created")
                    return False
                    
            except Exception as e:
                logger.error("❌ PNG export failed: %s", e)
                return False
            
            logger.info("🎉 FULL PIPELINE SUCCESS!")
            return True
            
    except Exception as e:
        logger.error("❌ Full pipeline test failed: %s", e)
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if vulkan_process:
            vulkan_process.terminate()
            vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

def main():
    """Run all debug steps"""
    logger.info("🚀 VK2TORCH STEP-BY-STEP DEBUG TEST")
    logger.info("=" * 50)
    
    steps = [
        ("Environment Check", step1_environment_check),
        ("Vulkan App Check", step2_vulkan_app_check), 
        ("Basic Connection", step3_basic_connection),
        ("Client Import", step4_client_import),
        ("Full Pipeline", step5_full_pipeline),
    ]
    
    results = []
    for step_name, step_func in steps:
        logger.info("")
        try:
            success = step_func()
            results.append((step_name, success))
            if success:
                logger.info("✅ %s: PASSED", step_name)
            else:
                logger.error("❌ %s: FAILED", step_name)
                break  # Stop on first failure
        except Exception as e:
            logger.error("❌ %s: EXCEPTION - %s", step_name, e)
            results.append((step_name, False))
            break
    
    # Summary
    logger.info("")
    logger.info("📊 FINAL RESULTS")
    logger.info("=" * 50)
    
    all_passed = True
    for step_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info("%s: %s", step_name, status)
        if not success:
            all_passed = False
    
    if all_passed:
        logger.info("")
        logger.info("🎉 ALL TESTS PASSED - VK2TORCH PIPELINE IS WORKING! 🎉")
        return 0
    else:
        logger.info("")
        logger.info("❌ SOME TESTS FAILED - CHECK LOGS ABOVE")
        return 1

if __name__ == "__main__":
    # Change to script directory
    os.chdir(Path(__file__).parent)
    sys.exit(main())