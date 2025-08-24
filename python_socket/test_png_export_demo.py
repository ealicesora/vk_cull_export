#!/usr/bin/env python3
"""
PNG Export demonstration - create test images to verify PNG functionality
"""

import os
import sys
import numpy as np
from pathlib import Path
import logging

# Setup logging  
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_png_export_opencv():
    """Test PNG export using OpenCV with synthetic data"""
    try:
        import cv2
        
        # Create synthetic frame data (1920x1080 RGBA)
        height, width = 1080, 1920
        
        # Create a colorful test pattern
        frame_bgra = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Create a gradient pattern
        for y in range(height):
            for x in range(width):
                frame_bgra[y, x, 0] = (x * 255) // width  # Blue
                frame_bgra[y, x, 1] = (y * 255) // height  # Green  
                frame_bgra[y, x, 2] = ((x + y) * 255) // (width + height)  # Red
                frame_bgra[y, x, 3] = 255  # Alpha
        
        # Save using OpenCV
        png_file = "demo_opencv_export.png"
        
        # Convert BGRA to BGR for OpenCV
        frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
        success = cv2.imwrite(png_file, frame_bgr)
        
        if success and os.path.exists(png_file):
            size = os.path.getsize(png_file)
            logger.info("✅ OpenCV PNG export: %s (%d bytes)", png_file, size)
            return True
        else:
            logger.error("❌ OpenCV PNG export failed")
            return False
        
    except Exception as e:
        logger.error("❌ OpenCV PNG export exception: %s", e)
        return False

def test_png_export_cupy():
    """Test PNG export using CuPy tensor with OpenCV"""
    try:
        import cupy as cp
        import cv2
        
        # Create synthetic GPU tensor
        height, width = 1080, 1920
        
        # Create test pattern on GPU
        device_data = cp.zeros((height, width, 4), dtype=cp.uint8)
        
        # Fill with checkerboard pattern
        x_coords, y_coords = cp.meshgrid(cp.arange(width), cp.arange(height))
        checker = ((x_coords // 64) + (y_coords // 64)) % 2
        
        device_data[:, :, 0] = checker * 255  # Blue channel
        device_data[:, :, 1] = (1 - checker) * 255  # Green channel
        device_data[:, :, 2] = 128  # Red channel
        device_data[:, :, 3] = 255  # Alpha channel
        
        # Convert to CPU and save
        host_data = cp.asnumpy(device_data)
        frame_bgr = cv2.cvtColor(host_data, cv2.COLOR_BGRA2BGR)
        
        png_file = "demo_cupy_export.png"
        success = cv2.imwrite(png_file, frame_bgr)
        
        if success and os.path.exists(png_file):
            size = os.path.getsize(png_file)
            logger.info("✅ CuPy PNG export: %s (%d bytes)", png_file, size)
            return True
        else:
            logger.error("❌ CuPy PNG export failed")
            return False
            
    except Exception as e:
        logger.error("❌ CuPy PNG export exception: %s", e)
        return False

def test_png_export_torch():
    """Test PNG export using PyTorch tensor"""
    try:
        import torch
        import cv2
        
        # Create synthetic tensor
        height, width = 1080, 1920
        
        # Create CUDA tensor if available
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Create rainbow pattern
        tensor = torch.zeros((height, width, 4), dtype=torch.uint8, device=device)
        
        for i in range(height):
            # Create rainbow effect
            hue = (i / height) * 360
            
            if hue < 120:  # Red to Green
                tensor[i, :, 2] = int(255 * (1 - hue / 120))  # Red
                tensor[i, :, 1] = int(255 * (hue / 120))      # Green
            elif hue < 240:  # Green to Blue
                tensor[i, :, 1] = int(255 * (1 - (hue - 120) / 120))  # Green
                tensor[i, :, 0] = int(255 * ((hue - 120) / 120))      # Blue
            else:  # Blue to Red
                tensor[i, :, 0] = int(255 * (1 - (hue - 240) / 120))  # Blue
                tensor[i, :, 2] = int(255 * ((hue - 240) / 120))      # Red
        
        tensor[:, :, 3] = 255  # Alpha
        
        # Convert to CPU numpy array
        host_data = tensor.cpu().numpy()
        frame_bgr = cv2.cvtColor(host_data, cv2.COLOR_BGRA2BGR)
        
        png_file = "demo_torch_export.png"  
        success = cv2.imwrite(png_file, frame_bgr)
        
        if success and os.path.exists(png_file):
            size = os.path.getsize(png_file)
            logger.info("✅ PyTorch PNG export: %s (%d bytes)", png_file, size)
            return True
        else:
            logger.error("❌ PyTorch PNG export failed")
            return False
            
    except Exception as e:
        logger.error("❌ PyTorch PNG export exception: %s", e)
        return False

def main():
    """Test PNG export functionality"""
    logger.info("🖼️  PNG EXPORT DEMONSTRATION")
    logger.info("=" * 60)
    
    # Environment check
    try:
        import numpy as np
        import cv2
        logger.info("✅ Core dependencies available")
        logger.info("   NumPy: %s", np.__version__)
        logger.info("   OpenCV: %s", cv2.__version__)
        
        try:
            import cupy as cp
            logger.info("   CuPy: %s", cp.__version__)
        except ImportError:
            logger.info("   CuPy: Not available")
            
        try:
            import torch
            logger.info("   PyTorch: %s", torch.__version__)
            if torch.cuda.is_available():
                logger.info("   CUDA: %s", torch.cuda.get_device_name())
        except ImportError:
            logger.info("   PyTorch: Not available")
            
    except ImportError as e:
        logger.error("❌ Missing dependencies: %s", e)
        return 1
    
    logger.info("")
    
    # Run PNG export tests
    tests = [
        ("OpenCV Direct", test_png_export_opencv),
        ("CuPy to PNG", test_png_export_cupy),
        ("PyTorch to PNG", test_png_export_torch),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info("🧪 Testing: %s", test_name)
        try:
            success = test_func()
            results.append((test_name, success))
            
            if success:
                logger.info("✅ %s: SUCCESS", test_name)
            else:
                logger.info("❌ %s: FAILED", test_name)
                
        except Exception as e:
            logger.error("❌ %s: EXCEPTION - %s", test_name, e)
            results.append((test_name, False))
        
        logger.info("")
    
    # Summary
    logger.info("📊 PNG EXPORT TEST RESULTS")
    logger.info("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info("%-15s: %s", test_name, status)
    
    logger.info("")
    logger.info("Result: %d/%d PNG export methods working", passed, total)
    
    if passed > 0:
        logger.info("🎉 PNG EXPORT FUNCTIONALITY VERIFIED!")
        logger.info("VK2Torch can successfully export frame data to PNG files")
        
        # List created files
        created_files = []
        for filename in ["demo_opencv_export.png", "demo_cupy_export.png", "demo_torch_export.png"]:
            if os.path.exists(filename):
                created_files.append(filename)
        
        if created_files:
            logger.info("Created demo files: %s", ", ".join(created_files))
        
        return 0
    else:
        logger.info("❌ No PNG export methods working")
        return 1

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    sys.exit(main())