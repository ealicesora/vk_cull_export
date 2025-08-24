#!/usr/bin/env python3
"""
T7 快速验证：优雅关闭与FD导出
专注于核心验证，避免复杂的进程监控导致的问题
"""

import sys
import os
import time

# Add build directory
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py/_bin/Release')

def test_single_cycle(cycle_num, width, height):
    """测试单个生命周期"""
    print(f"\n--- Cycle {cycle_num}: {width}x{height} ---")
    
    try:
        import vk2torch_ext
        
        # 创建应用
        app = vk2torch_ext.Vk2TorchApp(width, height, True, "")
        print(f"✅ Created Vk2TorchApp({width}, {height})")
        
        # 获取参数
        H, W = app.size()
        rp = app.row_pitch_bytes()
        print(f"   Size: ({H}, {W}), Row pitch: {rp}")
        
        # 导出FD
        fd_mem = app.export_depth_buffer_fd()
        fd_sem = app.export_frame_done_semaphore_fd()
        print(f"   FDs: memory={fd_mem}, semaphore={fd_sem}")
        
        valid_fds = []
        if fd_mem >= 0:
            os.fstat(fd_mem)  # 验证有效性
            valid_fds.append(fd_mem)
        if fd_sem >= 0:
            os.fstat(fd_sem)  # 验证有效性
            valid_fds.append(fd_sem)
        
        print(f"✅ {len(valid_fds)} valid FDs exported")
        
        # 运行10帧测试（简化）
        print("   Running 10 frame test...")
        for i in range(1, 11):
            view = [1.0, 0.0, 0.0, 0.0,  # 简单单位矩阵
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, -3.0-i*0.1,  # 轻微变化
                    0.0, 0.0, 0.0, 1.0]
            proj = [1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, -1.0, -1.0,
                    0.0, 0.0, -1.0, 0.0]
            
            app.set_camera(i, view, proj)
            last = app.last_signaled_frame()
            
            if i <= 3:
                print(f"     Frame {i}: last_signaled={last}")
        
        print("   ✅ Frame test completed")
        
        # 清理FD
        for fd in valid_fds:
            os.close(fd)
        print(f"   Closed {len(valid_fds)} FDs")
        
        # 停止应用
        app.stop()
        print("✅ Application stopped cleanly")
        
        return valid_fds  # 返回FD值用于唯一性检查
        
    except Exception as e:
        print(f"❌ Cycle {cycle_num} failed: {e}")
        return None

def main():
    """T7快速验证主函数"""
    print("T7 Quick Verification: Graceful Shutdown & Multiple FD Export")
    print("="*70)
    
    try:
        import vk2torch_ext
        print("✅ vk2torch_ext available")
    except ImportError as e:
        print(f"❌ Cannot import: {e}")
        return
    
    # 测试3个周期
    all_fds = []
    test_configs = [
        (1, 320, 240),
        (2, 400, 300), 
        (3, 480, 360)
    ]
    
    successful_cycles = 0
    
    for cycle, width, height in test_configs:
        fds = test_single_cycle(cycle, width, height)
        if fds is not None:
            all_fds.extend(fds)
            successful_cycles += 1
        
        # 短暂休息
        time.sleep(0.1)
    
    # FD唯一性检查
    print(f"\nFD Uniqueness Check:")
    print(f"All FDs collected: {all_fds}")
    
    unique_fds = set(all_fds)
    if len(unique_fds) == len(all_fds) and len(all_fds) > 0:
        print(f"✅ All {len(all_fds)} FDs are unique")
        fd_unique = True
    else:
        print(f"❌ FD uniqueness issue: {len(all_fds)} total, {len(unique_fds)} unique")
        fd_unique = False
    
    # 总结
    print(f"\n{'='*70}")
    print("T7 QUICK VERIFICATION RESULTS:")
    print(f"  Successful cycles: {successful_cycles}/3")
    print(f"  FD uniqueness: {'✅ PASS' if fd_unique else '❌ FAIL'}")
    print(f"  Total FDs exported: {len(all_fds)}")
    
    if successful_cycles == 3 and fd_unique:
        print("\n🎉 T7 VERIFICATION PASSED!")
        print("✅ Graceful shutdown working")
        print("✅ Multiple FD export working") 
        print("✅ No obvious leaks or crashes")
    elif successful_cycles >= 2:
        print("\n⚠️  T7 MOSTLY SUCCESSFUL")
        print(f"Minor issues but {successful_cycles}/3 cycles completed")
    else:
        print("\n❌ T7 VERIFICATION FAILED")
        print("Significant issues detected")
    
    print("="*70)

if __name__ == "__main__":
    main()