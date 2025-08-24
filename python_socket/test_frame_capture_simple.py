#!/usr/bin/env python3
"""
Simple frame capture test with PNG export - focused test
"""

import os
import sys
import subprocess
import time
import numpy as np
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_frame_capture():
    """Test frame capture with very simple approach"""
    socket_path = "/tmp/frame_test.sock"
    app_path = Path("../_bin/Release/vk_lod_clusters").resolve()
    
    # Clean up
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    
    logger.info("🖼️  TESTING FRAME CAPTURE WITH PNG EXPORT")
    logger.info("=" * 60)
    
    # Start Vulkan app
    cmd = [
        str(app_path),
        "--uds", socket_path,
        "--offscreen", "1",
        "--renderer", "0",
        "--validation", "0",
        "--gridcopies", "1"
    ]
    
    vulkan_process = None
    try:
        vulkan_process = subprocess.Popen(cmd, cwd=app_path.parent.parent)
        time.sleep(4)  # Give extra time for startup
        
        # Test with original client (has fallbacks)
        import vk2torch_client
        
        logger.info("✅ Using original client with graceful fallbacks")
        
        client = vk2torch_client.VK2TorchClient(socket_path)
        logger.info("✅ Client created")
        
        # Connect
        if not client.connect():
            logger.error("❌ Connection failed")
            return False
        
        logger.info("✅ Connected: %dx%d", client.width, client.height)
        logger.info("✅ CUDA available: %s", hasattr(client, 'cuda_available') and client.cuda_available)
        
        # Simple camera setup
        view_matrix = np.eye(4, dtype=np.float32)
        view_matrix[2, 3] = -5.0  # Move camera back
        proj_matrix = np.eye(4, dtype=np.float32)
        
        try:
            client.update_camera(view_matrix, proj_matrix)
            logger.info("✅ Camera update successful")
        except Exception as e:
            logger.error("❌ Camera update failed: %s", e)
            return False
        
        # Try frame capture with shorter timeout
        try:
            logger.info("Attempting frame capture...")
            frame = client.get_frame(timeout_ms=3000)  # 3 second timeout
            logger.info("✅ Frame captured: %s %s", frame.shape, frame.dtype)
            
            if hasattr(frame, 'device'):
                logger.info("   Device: %s", frame.device)
            
            # Try PNG export
            png_file = "frame_test_output.png"
            try:
                client.save_frame_png(frame, png_file)
                
                if os.path.exists(png_file):
                    size = os.path.getsize(png_file)
                    logger.info("✅ PNG saved: %s (%d bytes)", png_file, size)
                    logger.info("🎉 FRAME CAPTURE + PNG EXPORT SUCCESS!")
                    return True
                else:
                    logger.error("❌ PNG file not created")
                    return False
                    
            except Exception as e:
                logger.error("❌ PNG export failed: %s", e)
                return False
                
        except Exception as e:
            logger.error("❌ Frame capture failed: %s", e)
            return False
        
    except Exception as e:
        logger.error("❌ Test failed: %s", e)
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if vulkan_process:
            logger.info("Terminating Vulkan process...")
            vulkan_process.terminate()
            try:
                vulkan_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vulkan_process.kill()
                vulkan_process.wait()
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)

def main():
    """Main test function"""
    logger.info("Starting simple frame capture test...")
    
    # Basic environment check
    try:
        import numpy as np
        logger.info("✅ NumPy: %s", np.__version__)
        
        # Check optional dependencies
        try:
            import cupy as cp
            logger.info("✅ CuPy: %s", cp.__version__)
        except ImportError:
            logger.info("⚠️  CuPy not available")
        
        try:
            import torch
            logger.info("✅ PyTorch: %s", torch.__version__)
        except ImportError:
            logger.info("⚠️  PyTorch not available")
        
        try:
            import cv2
            logger.info("✅ OpenCV: %s", cv2.__version__)
        except ImportError:
            logger.info("⚠️  OpenCV not available")
        
    except ImportError as e:
        logger.error("❌ Basic dependencies missing: %s", e)
        return 1
    
    # Run test
    success = test_frame_capture()
    
    if success:
        logger.info("🎉 SIMPLE FRAME CAPTURE TEST: SUCCESS!")
        return 0
    else:
        logger.info("❌ SIMPLE FRAME CAPTURE TEST: FAILED")
        return 1

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    sys.exit(main())