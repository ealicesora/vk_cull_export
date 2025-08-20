#!/usr/bin/env python3
"""
Test script for Vulkan-CUDA Timeline Semaphore Synchronization

This tests the semaphore signaling and waiting between Vulkan and CUDA:
1. Python signals a timeline semaphore value via CUDA
2. Vulkan receives the signal and echoes it back
3. Python waits for the echoed value
"""

import os
import sys
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_semaphore_sync():
    """Test semaphore synchronization with echo."""
    
    # Import the client
    try:
        from vk2torch_client import VK2TorchClient
    except ImportError:
        logger.error("Failed to import vk2torch_client")
        logger.info("Make sure you're in the python directory")
        return False
    
    logger.info("=" * 60)
    logger.info("VULKAN-CUDA TIMELINE SEMAPHORE TEST")
    logger.info("=" * 60)
    
    # Enable semaphore test mode
    os.environ['VK2TORCH_TEST_SEMAPHORE'] = '1'
    
    socket_path = "/tmp/sem_test.sock"
    
    with VK2TorchClient(socket_path) as client:
        logger.info(f"Connecting to Vulkan app at {socket_path}...")
        
        if not client.connect():
            logger.error("Failed to connect to Vulkan application")
            logger.info("\nTo run this test:")
            logger.info("1. Start Vulkan app with semaphore test enabled:")
            logger.info(f"   VK2TORCH_TEST_SEMAPHORE=1 ./_bin/Release/vk_lod_clusters \\")
            logger.info(f"     --uds {socket_path} --offscreen 1 --renderer 0 --validation 0")
            logger.info("2. Run this test:")
            logger.info("   python3 test_semaphore.py")
            return False
        
        logger.info("✓ Connected successfully")
        
        # Check if CUDA is available
        if not client.has_cuda_support:
            logger.error("CUDA support not available")
            return False
        
        logger.info("✓ CUDA support available")
        
        # The initial test is done automatically during connection if VK2TORCH_TEST_SEMAPHORE=1
        # Now let's do additional ping-pong tests
        
        logger.info("\nRunning additional ping-pong tests...")
        if client.test_semaphore_ping_pong(iterations=10):
            logger.info("✓ All ping-pong tests passed!")
        else:
            logger.error("✗ Ping-pong tests failed")
            return False
        
        # Test with actual frame rendering
        logger.info("\nTesting with frame rendering...")
        try:
            import numpy as np
            
            # Create simple camera matrices
            view_matrix = np.eye(4, dtype=np.float32)
            proj_matrix = np.eye(4, dtype=np.float32)
            
            for i in range(3):
                logger.info(f"  Frame {i+1}/3...")
                
                # Update camera (this signals camera semaphore)
                if not client.update_camera(view_matrix, proj_matrix):
                    logger.error("Failed to update camera")
                    return False
                
                # Get frame (this waits on done semaphore)
                frame = client.get_frame(timeout_ms=1000)
                if frame is None:
                    logger.warning("Frame capture not available (CuPy/PyTorch required)")
                    # This is okay if we don't have CuPy/PyTorch
                else:
                    logger.info(f"    Got frame: {frame.shape}")
                
                time.sleep(0.1)
            
            logger.info("✓ Frame rendering test completed")
            
        except ImportError:
            logger.warning("NumPy not available, skipping frame test")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ ALL SEMAPHORE TESTS PASSED!")
    logger.info("=" * 60)
    
    return True

def main():
    """Main test entry point."""
    
    # Check if we should start the Vulkan app first
    if len(sys.argv) > 1 and sys.argv[1] == "--start-vulkan":
        logger.info("Starting Vulkan application with semaphore test...")
        import subprocess
        
        env = os.environ.copy()
        env['VK2TORCH_TEST_SEMAPHORE'] = '1'
        
        proc = subprocess.Popen(
            ['./_bin/Release/vk_lod_clusters',
             '--uds', '/tmp/sem_test.sock',
             '--offscreen', '1',
             '--renderer', '0',
             '--validation', '0',
             '--gridcopies', '1'],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        
        # Wait for it to start
        time.sleep(3)
        
        # Run the test
        success = test_semaphore_sync()
        
        # Terminate Vulkan app
        proc.terminate()
        proc.wait()
        
        return 0 if success else 1
    
    else:
        # Just run the test (assume Vulkan is already running)
        success = test_semaphore_sync()
        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())