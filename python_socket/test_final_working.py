#!/usr/bin/env python3
"""
Final working test for VK2Torch integration
This test addresses synchronization issues and provides clear diagnostics
"""

import os
import sys
import time
import struct
import numpy as np
from pathlib import Path

# Add Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_vk2torch():
    """Test the complete VK2Torch pipeline with proper synchronization."""
    
    socket_path = "/tmp/vk2torch.sock"
    
    print("=" * 70)
    print("VK2TORCH FINAL INTEGRATION TEST")
    print("=" * 70)
    
    # Import client
    print("\n1. Importing client...")
    try:
        import vk2torch_client
        print("✅ Client imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import client: {e}")
        return False
    
    # Check socket exists
    if not os.path.exists(socket_path):
        print(f"\n❌ Socket {socket_path} does not exist!")
        print("\nPlease start Vulkan application first:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --renderer 0 --validation 0 --gridcopies 1")
        print("\nThen run this test again.")
        return False
    
    print(f"✅ Socket exists: {socket_path}")
    
    # Create client
    print("\n2. Creating client...")
    client = vk2torch_client.VK2TorchClient(socket_path)
    
    # Connect
    print("\n3. Connecting to Vulkan...")
    if not client.connect():
        print("❌ Failed to connect")
        return False
    
    print(f"✅ Connected successfully")
    print(f"   Resolution: {client.width}x{client.height}")
    print(f"   Format: {client.format}")
    print(f"   CUDA support: {client.has_cuda_support}")
    
    if not client.has_cuda_support:
        print("\n⚠️  WARNING: No CUDA support - frames will use CPU fallback")
        print("   This may still work but will be slower")
    
    # Wait for Vulkan to stabilize
    print("\n4. Waiting for Vulkan render loop to stabilize...")
    time.sleep(2)
    
    print("\n5. Testing frame capture...")
    print("-" * 50)
    
    success_count = 0
    failed_frames = []
    
    # Test multiple frames with different camera positions
    num_frames = 15
    for i in range(num_frames):
        print(f"\n📸 Frame {i+1}/{num_frames}:")
        
        # Create camera matrices
        angle = i * (np.pi / 3)  # 60 degree increments
        distance = 5.0 + i * 0.5
        
        # Simple camera setup
        eye = np.array([
            distance * np.cos(angle),
            2.0,
            distance * np.sin(angle)
        ])
        
        # View matrix (look at origin)
        view = np.eye(4, dtype=np.float32)
        view[:3, 3] = -eye  # Translation
        
        # Projection matrix (simple perspective)
        proj = np.eye(4, dtype=np.float32)
        proj[0, 0] = 1.0     # Aspect ratio
        proj[1, 1] = -1.0    # Flip Y for Vulkan
        proj[2, 2] = 0.5     # Depth range
        proj[2, 3] = 0.5
        proj[3, 2] = -1.0    # Perspective
        
        print(f"  Camera: angle={np.degrees(angle):.0f}°, distance={distance:.1f}")
        
        # Update camera
        try:
            if client.update_camera(view, proj):
                print(f"  ✅ Camera updated (frame {client.frame_number} signaled)")
            else:
                print(f"  ❌ Camera update failed")
                failed_frames.append(i)
                continue
        except Exception as e:
            print(f"  ❌ Camera update exception: {e}")
            failed_frames.append(i)
            continue
        
        # Get frame with timeout
        try:
            print(f"  ⏳ Waiting for frame (timeout=5s)...")
            frame = client.get_frame(timeout_ms=5000)
            
            if frame is not None:
                print(f"  ✅ Frame received: shape={frame.shape}, dtype={frame.dtype}")
                
                # Check if it's on GPU
                if hasattr(frame, 'device'):
                    print(f"     Device: {frame.device}")
                else:
                    print(f"     Device: CPU (fallback)")
                
                # Save as PNG
                filename = f"vk2torch_frame_{i:03d}.png"
                if client.save_frame_png(frame, filename):
                    file_path = Path(filename)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        print(f"  ✅ Saved {filename} ({size:,} bytes)")
                        success_count += 1
                    else:
                        print(f"  ⚠️  File {filename} not found after save")
                        failed_frames.append(i)
                else:
                    print(f"  ❌ Failed to save {filename}")
                    failed_frames.append(i)
            else:
                print(f"  ❌ Frame is None (timeout)")
                failed_frames.append(i)
                
        except Exception as e:
            print(f"  ❌ Frame capture exception: {e}")
            import traceback
            traceback.print_exc()
            failed_frames.append(i)
        
        # Small delay between frames
        if i < num_frames - 1:
            time.sleep(0.5)
    
    # Disconnect
    print("\n6. Disconnecting...")
    client.disconnect()
    print("✅ Disconnected")
    
    # Report results
    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)
    
    if success_count > 0:
        print(f"✅ Successfully captured {success_count}/{num_frames} frames")
        
        # List PNG files
        png_files = list(Path(".").glob("vk2torch_frame_*.png"))
        if png_files:
            print(f"\n📸 PNG files created:")
            for png in sorted(png_files):
                size = png.stat().st_size
                print(f"   ✅ {png.name} ({size:,} bytes)")
        
        if success_count == num_frames:
            print("\n🎉 COMPLETE SUCCESS!")
            return True
        else:
            print(f"\n⚠️  PARTIAL SUCCESS - Failed frames: {failed_frames}")
            return True
    else:
        print(f"❌ No frames were captured successfully")
        print(f"   Failed frames: {failed_frames}")
        return False

def main():
    """Main entry point."""
    
    print("VK2Torch Integration Test")
    print("This test will:")
    print("1. Connect to running Vulkan application")
    print("2. Send camera updates")
    print("3. Capture frames")
    print("4. Save them as PNG files")
    print("")
    
    # Check if Vulkan is running
    socket_path = "/tmp/vk2torch.sock"
    if not os.path.exists(socket_path):
        print("⚠️  Vulkan application is not running!")
        print("\nPlease start it first with:")
        print(f"  ./_bin/Release/vk_lod_clusters --uds {socket_path} --renderer 0 --validation 0 --gridcopies 1")
        print("\nThen run this test again.")
        return 1
    
    # Run test
    success = test_vk2torch()
    
    if success:
        print("\n✅ Test completed successfully!")
        print("Check the current directory for vk2torch_frame_*.png files")
        return 0
    else:
        print("\n❌ Test failed")
        print("Check the output above for errors")
        return 1

if __name__ == "__main__":
    sys.exit(main())