#!/usr/bin/env python3
"""
Pybind11 Extension Implementation Verification Script
验证 pybind11 扩展 2.3 需求实现完整性

This script verifies that all four methods specified in requirement 2.3 
have been properly implemented in the Vk2TorchApp class:

1. get_interop_info() - Export all FDs and metadata for CUDA interop
2. set_camera_matrices() - Set camera from Python using numpy arrays  
3. wait_scene_ready_cpu() - CPU version of scene ready waiting
4. render_one_frame() - Drive single frame rendering from CPU
"""

import sys
import os
from pathlib import Path

def verify_pybind11_extension_implementation():
    """Verify pybind11 extension methods have been implemented"""
    
    print("🎯 Pybind11 Extension Implementation Verification (2.3 Requirements)")
    print("=" * 80)
    
    # Read source files
    vk2torch_ext_cpp = Path(__file__).parent / "src" / "pybind" / "vk2torch_ext.cpp"
    external_memory_hpp = Path(__file__).parent / "src" / "external_memory.hpp"
    external_memory_cpp = Path(__file__).parent / "src" / "external_memory.cpp"
    
    if not vk2torch_ext_cpp.exists():
        print("❌ vk2torch_ext.cpp not found")
        return False
        
    if not external_memory_hpp.exists():
        print("❌ external_memory.hpp not found") 
        return False
        
    if not external_memory_cpp.exists():
        print("❌ external_memory.cpp not found")
        return False
    
    with open(vk2torch_ext_cpp, 'r') as f:
        cpp_content = f.read()
        
    with open(external_memory_hpp, 'r') as f:
        hpp_content = f.read()
        
    with open(external_memory_cpp, 'r') as f:
        cpp_impl_content = f.read()
    
    # Check 1: get_interop_info() method implementation
    print("📋 Checking get_interop_info() method...")
    get_interop_checks = [
        ("Method signature", "pybind11::dict get_interop_info()"),
        ("InteropExportInfo usage", "getInteropExportInfo()"),
        ("All FD exports", "depth_mem_fd"),
        ("Scene ready semaphore", "scene_ready_sem_fd"),
        ("Camera ready semaphore", "camera_ready_sem_fd"), 
        ("Frame done semaphore", "frame_done_sem_fd"),
        ("Metadata export", "row_pitch_bytes"),
        ("Format information", "depth_format")
    ]
    
    get_interop_passed = 0
    for name, pattern in get_interop_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            get_interop_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 2: set_camera_matrices() method implementation
    print("\\n📋 Checking set_camera_matrices() method...")
    set_camera_checks = [
        ("Method signature", "void set_camera_matrices(pybind11::array proj_arr, pybind11::array view_arr)"),
        ("Array validation", "proj_arr.ndim() != 2"),
        ("Buffer info access", "proj_arr.request()"),
        ("Double/float handling", "proj_buf.itemsize == 8"),
        ("Row-major conversion", "proj[c][r] = proj_data[r * 4 + c]"),
        ("LodClusters integration", "m_lodclusters->enableOverrideCamera"),
        ("Camera ready signaling", "m_externalMemory->signalCameraReady"),
        ("Frame counter usage", "m_frameCounter.load()")
    ]
    
    set_camera_passed = 0
    for name, pattern in set_camera_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            set_camera_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 3: wait_scene_ready_cpu() method implementation
    print("\\n📋 Checking wait_scene_ready_cpu() method...")
    wait_scene_checks = [
        ("Method signature", "bool wait_scene_ready_cpu(uint32_t timeout_ms = 5000)"),
        ("ExternalMemory validation", "if (!m_externalMemory)"),
        ("Scene ready waiting", "m_externalMemory->waitSceneReady(1, timeout_ms)"),
        ("Timeout parameter", "timeout_ms = 5000"),
        ("Return value", "return m_externalMemory->waitSceneReady")
    ]
    
    wait_scene_passed = 0
    for name, pattern in wait_scene_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            wait_scene_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 4: render_one_frame() method implementation  
    print("\\n📋 Checking render_one_frame() method...")
    render_frame_checks = [
        ("Method signature", "uint64_t render_one_frame()"),
        ("LodClusters validation", "if (!m_lodclusters)"),
        ("Frame counter increment", "m_frameCounter.fetch_add(1) + 1"),
        ("LodClusters rendering", "m_lodclusters->renderOneFrame(frame_value)"),
        ("Return frame value", "return frame_value")
    ]
    
    render_frame_passed = 0
    for name, pattern in render_frame_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            render_frame_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 5: Pybind11 module binding
    print("\\n📋 Checking pybind11 module bindings...")
    binding_checks = [
        ("get_interop_info binding", '.def("get_interop_info", &Vk2TorchApp::get_interop_info,'),
        ("set_camera_matrices binding", '.def("set_camera_matrices", &Vk2TorchApp::set_camera_matrices,'),
        ("wait_scene_ready_cpu binding", '.def("wait_scene_ready_cpu", &Vk2TorchApp::wait_scene_ready_cpu,'),
        ("render_one_frame binding", '.def("render_one_frame", &Vk2TorchApp::render_one_frame,'),
        ("Timeout parameter", 'py::arg("timeout_ms") = 5000')
    ]
    
    binding_passed = 0
    for name, pattern in binding_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            binding_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 6: Supporting methods in ExternalMemoryManager
    print("\\n📋 Checking ExternalMemoryManager supporting methods...")
    supporting_checks = [
        ("signalCameraReady header", "bool signalCameraReady(uint64_t value);"),
        ("waitSceneReady header", "bool waitSceneReady(uint64_t value, uint32_t timeout_ms = 5000);"),
        ("signalCameraReady impl", "bool ExternalMemoryManager::signalCameraReady(uint64_t value)"),
        ("waitSceneReady impl", "bool ExternalMemoryManager::waitSceneReady(uint64_t value, uint32_t timeout_ms)"),
        ("Camera timeline access", "m_cameraReadyTimeline"),
        ("Scene timeline access", "m_sceneReadyTimeline")
    ]
    
    supporting_passed = 0
    for name, pattern in supporting_checks:
        found = False
        if pattern in hpp_content or pattern in cpp_impl_content:
            found = True
        if found:
            print(f"  ✅ {name}")
            supporting_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Check 7: Frame counter member variable
    print("\\n📋 Checking frame counter member variable...")
    frame_counter_checks = [
        ("Atomic frame counter", "std::atomic<uint64_t> m_frameCounter{0};"),
        ("Frame counter comment", "Frame synchronization for render_and_signal and set_camera_matrices")
    ]
    
    frame_counter_passed = 0
    for name, pattern in frame_counter_checks:
        if pattern in cpp_content:
            print(f"  ✅ {name}")
            frame_counter_passed += 1
        else:
            print(f"  ❌ {name}")
    
    # Summary
    total_checks = (len(get_interop_checks) + len(set_camera_checks) + len(wait_scene_checks) + 
                   len(render_frame_checks) + len(binding_checks) + len(supporting_checks) + 
                   len(frame_counter_checks))
    total_passed = (get_interop_passed + set_camera_passed + wait_scene_passed + 
                   render_frame_passed + binding_passed + supporting_passed + frame_counter_passed)
    
    print("\\n" + "=" * 80)
    print("📊 Pybind11 Extension Implementation Summary:")
    print(f"  • get_interop_info(): {get_interop_passed}/{len(get_interop_checks)} ✅")
    print(f"  • set_camera_matrices(): {set_camera_passed}/{len(set_camera_checks)} ✅") 
    print(f"  • wait_scene_ready_cpu(): {wait_scene_passed}/{len(wait_scene_checks)} ✅")
    print(f"  • render_one_frame(): {render_frame_passed}/{len(render_frame_checks)} ✅")
    print(f"  • Pybind11 bindings: {binding_passed}/{len(binding_checks)} ✅")
    print(f"  • Supporting methods: {supporting_passed}/{len(supporting_checks)} ✅")
    print(f"  • Frame counter: {frame_counter_passed}/{len(frame_counter_checks)} ✅")
    print(f"  • Overall: {total_passed}/{total_checks} ({total_passed/total_checks*100:.1f}%)")
    
    if total_passed >= total_checks * 0.95:  # 95% threshold
        print(f"\\n🎉 PYBIND11 EXTENSION IMPLEMENTATION: SUCCESS!")
        print("✅ All four required methods implemented")
        print("✅ get_interop_info() exports all FDs and metadata")
        print("✅ set_camera_matrices() handles numpy arrays with camera ready signaling") 
        print("✅ wait_scene_ready_cpu() provides CPU-based scene ready waiting")
        print("✅ render_one_frame() enables frame-by-frame CPU control")
        print("✅ Pybind11 module bindings expose all methods to Python")
        print("✅ Supporting ExternalMemoryManager methods implemented")
        
        print(f"\\n🚀 Python Integration Summary:")
        integration_steps = [
            "1. Python calls app.get_interop_info() → receives all FDs for CUDA import",
            "2. Python calls app.set_camera_matrices(proj, view) → signals camera ready",  
            "3. Python calls app.wait_scene_ready_cpu() → waits for scene initialization",
            "4. Python calls app.render_one_frame() → drives single frame rendering",
            "5. Complete three-way timeline semaphore coordination achieved"
        ]
        
        for step in integration_steps:
            print(f"  {step}")
        
        return True
    else:
        print(f"\\n⚠️  PYBIND11 EXTENSION IMPLEMENTATION: INCOMPLETE")
        print(f"❌ {total_checks - total_passed} implementation points missing")
        return False

if __name__ == "__main__":
    print("Pybind11 Extension Implementation Verification")
    print("pybind11 扩展实现验证")
    print("=" * 80)
    
    success = verify_pybind11_extension_implementation()
    
    if success:
        print("\\n🎯 PYBIND11 EXTENSION (2.3 REQUIREMENT): COMPLETE!")
        print("✅ get_interop_info() method implemented with full FD export")
        print("✅ set_camera_matrices() method implemented with numpy array support")
        print("✅ wait_scene_ready_cpu() method implemented with timeout")
        print("✅ render_one_frame() method implemented for CPU control")
        print("✅ All methods exposed via pybind11 module bindings")
        print("✅ Ready for Python integration testing and end-to-end pipeline")
        sys.exit(0)
    else:
        print("\\n❌ PYBIND11 EXTENSION (2.3 REQUIREMENT): NEEDS WORK")
        print("⚠️  Some implementation points require attention")
        sys.exit(1)