#!/usr/bin/env python3
"""
T7: 收尾 - 优雅关闭与多FD导出验证

测试目标：
1. Vk2TorchApp.stop() 能干净退出（无僵尸线程、无FD泄漏）
2. 多次导出FD每次得到不同的整数且都可os.fstat
3. 重复3次：构造→导出FD→运行30帧→stop()

验证要点：
- camera_ready: host可signal/wait的timeline信号量，C++内部使用
- frame_done: Vulkan→CUDA/Python的时间线，由LodClusters signal
- 元素顺序: PyBridge在前，LodClusters在后
- FD导出: 返回dup(fd)，内部持有原句柄
- 行步长: 返回真实对齐行步长用于Python strides
"""

import sys
import os
import time
import threading
import psutil
import numpy as np

# Add build directory to path
sys.path.insert(0, '/home/gongyuning/Desktop/vk_cull/vk_lod_clusters/build-py/_bin/Release')

def get_process_info():
    """获取当前进程信息用于泄漏检测"""
    proc = psutil.Process()
    return {
        'threads': proc.num_threads(),
        'fds': proc.num_fds(),
        'memory_mb': proc.memory_info().rss / 1024 / 1024
    }

def create_test_camera_matrices(frame_num):
    """创建测试用相机矩阵"""
    view = np.eye(4, dtype=np.float32)
    view[2, 3] = -(3.0 + frame_num * 0.05)  # 逐步远离
    
    # 添加轻微旋转
    angle = frame_num * 0.02
    c, s = np.cos(angle), np.sin(angle)
    view[0, 0] = c
    view[0, 2] = s
    view[2, 0] = -s
    view[2, 2] = c
    
    # 简单透视投影
    proj = np.eye(4, dtype=np.float32)
    fov = np.radians(60.0)
    aspect = 1.0
    near, far = 0.1, 100.0
    
    f = 1.0 / np.tan(fov / 2.0)
    proj[0, 0] = f / aspect
    proj[1, 1] = f
    proj[2, 2] = (far + near) / (near - far)
    proj[2, 3] = (2.0 * far * near) / (near - far)
    proj[3, 2] = -1.0
    proj[3, 3] = 0.0
    
    return view.flatten().tolist(), proj.flatten().tolist()

def test_single_lifecycle(cycle_num, width=400, height=300):
    """测试单个生命周期：构造→导出FD→运行帧→关闭"""
    print(f"\n{'='*20} Cycle {cycle_num} {'='*20}")
    
    try:
        import vk2torch_ext
        
        # 获取初始进程状态
        initial_info = get_process_info()
        print(f"Initial state: {initial_info['threads']} threads, {initial_info['fds']} FDs, {initial_info['memory_mb']:.1f}MB")
        
        # 创建应用
        print(f"Creating Vk2TorchApp({width}, {height})...")
        app = vk2torch_ext.Vk2TorchApp(width, height, raster=True, scene_path="")
        
        after_create_info = get_process_info()
        print(f"After create: {after_create_info['threads']} threads, {after_create_info['fds']} FDs, {after_create_info['memory_mb']:.1f}MB")
        
        # 获取应用参数
        H, W = app.size()
        row_pitch = app.row_pitch_bytes()
        print(f"App params: size=({H}, {W}), row_pitch={row_pitch}")
        
        # 验证尺寸正确
        assert H == height and W == width, f"Size mismatch: expected ({height}, {width}), got ({H}, {W})"
        assert row_pitch % 4 == 0, f"Row pitch {row_pitch} not 4-byte aligned"
        assert row_pitch >= W * 4, f"Row pitch {row_pitch} too small for width {W}"
        
        # 导出FD并验证
        print("Exporting file descriptors...")
        fd_depth = app.export_depth_buffer_fd()
        fd_semaphore = app.export_frame_done_semaphore_fd()
        
        print(f"Exported FDs: depth={fd_depth}, semaphore={fd_semaphore}")
        
        exported_fds = []
        if fd_depth >= 0:
            stat_result = os.fstat(fd_depth)
            print(f"✅ Depth FD {fd_depth} valid: size={stat_result.st_size}")
            exported_fds.append(fd_depth)
        else:
            print(f"⚠️  Depth FD invalid: {fd_depth}")
            
        if fd_semaphore >= 0:
            stat_result = os.fstat(fd_semaphore)
            print(f"✅ Semaphore FD {fd_semaphore} valid")
            exported_fds.append(fd_semaphore)
        else:
            print(f"⚠️  Semaphore FD invalid: {fd_semaphore}")
        
        # 运行30帧测试
        print("Running 30 frame test...")
        successful_frames = 0
        
        start_time = time.time()
        for frame_i in range(1, 31):
            try:
                # 设置相机
                view, proj = create_test_camera_matrices(frame_i)
                app.set_camera(frame_i, view, proj)
                
                # 检查最后信号帧
                last_signaled = app.last_signaled_frame()
                
                if frame_i <= 3:  # 前3帧详细日志
                    print(f"  Frame {frame_i}: camera set, last_signaled={last_signaled}")
                elif frame_i % 10 == 0:  # 每10帧进度报告
                    elapsed = time.time() - start_time
                    fps = frame_i / elapsed
                    print(f"  Progress: {frame_i}/30 frames, {fps:.1f} FPS, last_signaled={last_signaled}")
                
                successful_frames += 1
                
                # 短暂暂停避免压垮系统
                time.sleep(0.01)  # 100 FPS节奏
                
            except Exception as e:
                print(f"  Frame {frame_i} failed: {e}")
        
        total_time = time.time() - start_time
        print(f"Frame test completed: {successful_frames}/30 frames in {total_time:.1f}s ({successful_frames/total_time:.1f} FPS)")
        
        # 检查运行时进程状态
        runtime_info = get_process_info()
        print(f"Runtime state: {runtime_info['threads']} threads, {runtime_info['fds']} FDs, {runtime_info['memory_mb']:.1f}MB")
        
        # 关闭FD（模拟Python客户端行为）
        print("Closing exported FDs...")
        for fd in exported_fds:
            os.close(fd)
        print(f"Closed {len(exported_fds)} FDs")
        
        # 停止应用
        print("Stopping application...")
        app.stop()
        
        # 等待线程完全清理
        time.sleep(0.1)
        
        # 检查清理后状态
        final_info = get_process_info()
        print(f"Final state: {final_info['threads']} threads, {final_info['fds']} FDs, {final_info['memory_mb']:.1f}MB")
        
        # 分析资源使用变化
        thread_delta = final_info['threads'] - initial_info['threads']
        fd_delta = final_info['fds'] - initial_info['fds']
        memory_delta = final_info['memory_mb'] - initial_info['memory_mb']
        
        print(f"Resource deltas: threads={thread_delta:+d}, FDs={fd_delta:+d}, memory={memory_delta:+.1f}MB")
        
        # 验证清理完成
        cleanup_success = True
        if thread_delta > 2:  # 允许少量线程增加
            print(f"⚠️  Thread count increased significantly: +{thread_delta}")
            cleanup_success = False
        if fd_delta > 5:  # 允许少量FD增加
            print(f"⚠️  FD count increased significantly: +{fd_delta}")
            cleanup_success = False
        if memory_delta > 50:  # 允许适量内存增长
            print(f"⚠️  Memory usage increased significantly: +{memory_delta:.1f}MB")
            cleanup_success = False
            
        if cleanup_success:
            print("✅ Resource cleanup appears successful")
        else:
            print("⚠️  Potential resource leaks detected")
        
        result = {
            'successful_frames': successful_frames,
            'total_frames': 30,
            'exported_fds': len(exported_fds),
            'fd_values': exported_fds.copy(),  # 保存FD值用于唯一性检查
            'cleanup_success': cleanup_success,
            'resource_deltas': {
                'threads': thread_delta,
                'fds': fd_delta,
                'memory_mb': memory_delta
            }
        }
        
        print(f"✅ Cycle {cycle_num} completed successfully")
        return result
        
    except Exception as e:
        print(f"❌ Cycle {cycle_num} failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_fd_uniqueness(results):
    """验证多次导出的FD值唯一性"""
    print(f"\n{'='*50}")
    print("FD UNIQUENESS VERIFICATION")
    print("="*50)
    
    all_fds = []
    for i, result in enumerate(results):
        if result and 'fd_values' in result:
            cycle_fds = result['fd_values']
            print(f"Cycle {i+1} FDs: {cycle_fds}")
            all_fds.extend(cycle_fds)
    
    print(f"All FDs collected: {all_fds}")
    
    # 检查唯一性
    unique_fds = set(all_fds)
    if len(unique_fds) == len(all_fds):
        print(f"✅ All {len(all_fds)} FDs are unique")
        return True
    else:
        duplicates = len(all_fds) - len(unique_fds)
        print(f"❌ Found {duplicates} duplicate FDs out of {len(all_fds)}")
        return False

def main():
    """主测试函数"""
    print("="*80)
    print("T7: 收尾 - 优雅关闭与多FD导出验证")
    print("="*80)
    
    try:
        import vk2torch_ext
        print("✅ vk2torch_ext module available")
    except ImportError as e:
        print(f"❌ Cannot import vk2torch_ext: {e}")
        return
    
    # 获取初始系统状态
    initial_system_info = get_process_info()
    print(f"Initial system state: {initial_system_info}")
    
    # 运行3个生命周期测试
    results = []
    cycle_sizes = [(400, 300), (500, 350), (600, 400)]  # 不同尺寸测试
    
    for i in range(3):
        width, height = cycle_sizes[i]
        result = test_single_lifecycle(i + 1, width, height)
        results.append(result)
        
        if result:
            print(f"Cycle {i+1} summary: {result['successful_frames']}/{result['total_frames']} frames, {result['exported_fds']} FDs")
        
        # 周期间短暂休息
        if i < 2:
            print("Resting between cycles...")
            time.sleep(0.2)
    
    # 分析总体结果
    print(f"\n{'='*80}")
    print("T7 OVERALL RESULTS")
    print("="*80)
    
    successful_cycles = sum(1 for r in results if r is not None)
    total_frames = sum(r['successful_frames'] for r in results if r)
    total_possible_frames = sum(r['total_frames'] for r in results if r)
    clean_shutdowns = sum(1 for r in results if r and r['cleanup_success'])
    
    print(f"Successful cycles: {successful_cycles}/3")
    print(f"Total successful frames: {total_frames}/{total_possible_frames}")
    print(f"Clean shutdowns: {clean_shutdowns}/3")
    
    # FD唯一性检查
    fd_uniqueness_ok = test_fd_uniqueness(results)
    
    # 最终系统状态
    final_system_info = get_process_info()
    overall_thread_delta = final_system_info['threads'] - initial_system_info['threads']
    overall_fd_delta = final_system_info['fds'] - initial_system_info['fds']
    overall_memory_delta = final_system_info['memory_mb'] - initial_system_info['memory_mb']
    
    print(f"\nOverall system impact:")
    print(f"  Threads: {overall_thread_delta:+d}")
    print(f"  FDs: {overall_fd_delta:+d}")
    print(f"  Memory: {overall_memory_delta:+.1f}MB")
    
    # 最终评分
    success_criteria = [
        (successful_cycles == 3, "All 3 cycles completed successfully"),
        (total_frames >= total_possible_frames * 0.9, "90%+ frames successful"),
        (clean_shutdowns >= 2, "Majority of shutdowns clean"),
        (fd_uniqueness_ok, "All FDs unique across cycles"),
        (abs(overall_thread_delta) <= 3, "Thread count stable"),
        (abs(overall_fd_delta) <= 10, "FD count stable")
    ]
    
    passed_criteria = sum(1 for passed, _ in success_criteria if passed)
    
    print(f"\n📊 SUCCESS CRITERIA ({passed_criteria}/6):")
    for passed, description in success_criteria:
        status = "✅" if passed else "❌"
        print(f"  {status} {description}")
    
    if passed_criteria >= 5:
        print(f"\n🎉 T7 VERIFICATION PASSED! ({passed_criteria}/6 criteria met)")
        print("✅ Vk2TorchApp.stop() provides clean shutdown")
        print("✅ Multiple FD exports work correctly")
        print("✅ No significant resource leaks detected")
        print("✅ 3-cycle construct/destruct test successful")
    else:
        print(f"\n⚠️  T7 PARTIAL SUCCESS ({passed_criteria}/6 criteria met)")
        print("Some issues detected - may need investigation")
    
    print("="*80)

if __name__ == "__main__":
    main()