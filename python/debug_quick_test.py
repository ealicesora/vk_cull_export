#!/usr/bin/env python3
"""
Quick VK2Torch test - focused on core functionality without hanging
"""

import os
import sys
import subprocess
import time
import signal
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

def test_with_timeout():
    """Test with automatic timeout"""
    socket_path = "/tmp/debug_quick.sock"
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    
    # Clean up
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
    
    logger.info("🚀 Starting quick VK2Torch test")
    logger.info("Command: %s", ' '.join(cmd))
    
    vulkan_process = None
    try:
        vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
        time.sleep(3)  # Wait for startup
        
        # Test with strict client
        import vk2torch_client_strict_fixed
        import numpy as np
        
        logger.info("✅ Environment ready")
        logger.info("✅ Client imported")
        
        with vk2torch_client_strict_fixed.VK2TorchClientStrictFixed(socket_path) as client:
            logger.info("✅ Client created")
            
            # Set timeout for connection
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(10)  # 10 second timeout
            
            try:
                connected = client.connect()
                signal.alarm(0)  # Cancel timeout
                
                if not connected:
                    logger.error("❌ Connection failed")
                    return False
                
                logger.info("✅ Connected: %dx%d", client.width, client.height)
                logger.info("✅ CUDA support: %s", client.has_strict_cuda_support)
                
                if client.has_strict_cuda_support:
                    # Quick camera test
                    view = np.eye(4, dtype=np.float32) 
                    proj = np.eye(4, dtype=np.float32)
                    
                    signal.alarm(5)  # 5 second timeout for camera
                    client.update_camera(view, proj)
                    signal.alarm(0)
                    logger.info("✅ Camera update successful")
                    
                    # Quick frame test with short timeout
                    signal.alarm(10)  # 10 second timeout for frame
                    frame = client.get_frame(timeout_ms=5000)
                    signal.alarm(0)
                    
                    logger.info("✅ Frame: %s %s on %s", frame.shape, frame.dtype, frame.device)
                    
                    # PNG save test
                    try:
                        png_file = "quick_test.png"
                        client.save_frame_png(frame, png_file)
                        
                        if os.path.exists(png_file):
                            size = os.path.getsize(png_file)
                            logger.info("✅ PNG saved: %s (%d bytes)", png_file, size)
                        
                    except Exception as e:
                        logger.warning("⚠️  PNG save failed: %s", e)
                    
                    logger.info("🎉 QUICK TEST SUCCESS!")
                    return True
                else:
                    logger.info("✅ Basic connection works (CUDA not available)")
                    return True
                    
            except TimeoutError:
                signal.alarm(0)
                logger.error("❌ Operation timed out")
                return False
            except Exception as e:
                signal.alarm(0)
                logger.error("❌ Test failed: %s", e)
                return False
        
    except Exception as e:
        logger.error("❌ Test setup failed: %s", e)
        return False
    
    finally:
        signal.alarm(0)  # Make sure timeout is cancelled
        
        if vulkan_process:
            logger.info("Terminating Vulkan process...")
            vulkan_process.terminate()
            
            # Wait with timeout
            try:
                vulkan_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing Vulkan process...")
                vulkan_process.kill()
                vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

def main():
    """Main test function"""
    logger.info("=" * 60)
    logger.info("🧪 VK2TORCH QUICK TEST")
    logger.info("=" * 60)
    
    # Environment check first
    try:
        import numpy as np
        import cupy as cp
        import torch
        logger.info("✅ Core packages available")
        logger.info("   NumPy: %s", np.__version__)  
        logger.info("   CuPy: %s", cp.__version__)
        logger.info("   PyTorch: %s", torch.__version__)
        
        if torch.cuda.is_available():
            logger.info("   CUDA: %s", torch.cuda.get_device_name())
        
    except ImportError as e:
        logger.error("❌ Package missing: %s", e)
        return 1
    
    # Run the test
    success = test_with_timeout()
    
    logger.info("=" * 60)
    if success:
        logger.info("🎉 QUICK TEST PASSED - VK2TORCH WORKING!")
    else:
        logger.info("❌ QUICK TEST FAILED")
    logger.info("=" * 60)
    
    return 0 if success else 1

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    sys.exit(main())