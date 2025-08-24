/*
* Copyright (c) 2024-2025, NVIDIA CORPORATION.  All rights reserved.
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
*
* SPDX-FileCopyrightText: Copyright (c) 2024-2025, NVIDIA CORPORATION.
* SPDX-License-Identifier: Apache-2.0
*/

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include <array>
#include <string>
#include <utility>
#include <cstdint>
#include <thread>
#include <memory>
#include <mutex>
#include <atomic>
#include <cstdio>
#include <condition_variable>
#include <chrono>

// Vulkan and nvpro_core2 includes
#include <vulkan/vulkan.h>
#include <nvvk/context.hpp>
#include <nvvk/check_error.hpp>
#include <nvvk/debug_util.hpp>
#include <nvapp/application.hpp>
#include <nvutils/logger.hpp>
#include <nvutils/camera_manipulator.hpp>
#include <filesystem>

// Project includes
#include "core/context_bootstrap.hpp"
#include "pybridge/element_pybridge.hpp"
#include "external_memory.hpp"
#include "lodclusters.hpp"
#include "scene.hpp"

/**
 * Vk2TorchApp - Main interface class for in-process VK2Torch integration
 * 
 * This class creates and manages an nvapp::Application running in headless mode,
 * with LodClusters and ElementPyBridge components for zero-copy CUDA integration.
 */
class Vk2TorchApp {
public:
    /**
     * Constructor - Creates and starts headless Application with LOD rendering
     * @param width Render target width
     * @param height Render target height
     * @param raster Whether to use rasterization (true) or ray tracing (false)
     * @param scene_path Path to GLTF scene file (default: "matrix_city.glb")
     */
    Vk2TorchApp(int width, int height, bool raster = true, const std::string& scene_path = "matrix_city.glb")
        : m_width(width), m_height(height), m_raster(raster), m_scene_path(scene_path)
    {
        pybind11::gil_scoped_release release;  // Release GIL during initialization
        
        try {
            initializeVulkan();
            createApplication();
            startRenderThread();  // Scene will be loaded inside render thread
            
            printf("Vk2TorchApp: Successfully initialized with real 3D rendering\n");
        }
        catch (const std::exception& e) {
            cleanup();
            throw;
        }
    }

    /**
     * Destructor - stops Application and cleans up resources
     */
    ~Vk2TorchApp() {
        stop();
    }

    /**
     * Get render target dimensions
     * @return {height, width} pair
     */
    std::pair<int, int> size() const {
        return {m_height, m_width};
    }

    /**
     * Get row pitch in bytes for the exported buffer
     * @return Row pitch in bytes from ExternalMemoryManager
     */
    int row_pitch_bytes() const {
        if (m_pybridge) {
            return m_pybridge->rowPitchBytes();
        }
        return m_width * 4;  // Fallback
    }

    /**
     * Export depth buffer file descriptor for CUDA import
     * @return Duplicated file descriptor (caller must close)
     */
    int export_depth_buffer_fd() const {
        if (m_pybridge) {
            return m_pybridge->exportDepthBufferFdDup();
        }
        printf("Vk2TorchApp: export_depth_buffer_fd() - not ready\n");
        return -1;  // Not ready
    }

    /**
     * Export frame done timeline semaphore file descriptor
     * @return Duplicated file descriptor (caller must close)
     */
    int export_frame_done_semaphore_fd() const {
        if (m_pybridge) {
            return m_pybridge->exportFrameDoneSemaphoreFdDup();
        }
        printf("Vk2TorchApp: export_frame_done_semaphore_fd() - not ready\n");
        return -1;  // Not ready
    }

    /**
     * Set camera matrices and frame number
     * @param frame Frame number for synchronization
     * @param view 4x4 view matrix in column-major order
     * @param proj 4x4 projection matrix in column-major order
     */
    void set_camera(uint64_t frame, const std::array<float, 16>& view, const std::array<float, 16>& proj) {
        if (m_pybridge) {
            m_pybridge->updateCameraAndSignal(frame, view.data(), proj.data());
        } else {
            printf("Vk2TorchApp: set_camera(frame=%lu) - not ready\n", frame);
        }
    }

    /**
     * Get the last signaled frame number
     * @return Timeline semaphore value for last completed frame
     */
    uint64_t last_signaled_frame() const {
        if (m_pybridge) {
            return m_pybridge->lastSignaledFrame();
        }
        return 0;
    }

    /**
     * Stop the Application and cleanup resources
     */
    void stop() {
        printf("Vk2TorchApp: Stopping...\n");
        
        {
            std::lock_guard<std::mutex> lock(m_stopMutex);
            if (m_running) {
                m_running = false;
                if (m_app) {
                    m_app->close();
                }
            }
        }
        
        if (m_renderThread.joinable()) {
            m_renderThread.join();
        }
        
        cleanup();
        printf("Vk2TorchApp: Stopped\n");
    }

private:
    // Configuration
    int m_width;
    int m_height;
    bool m_raster;
    std::string m_scene_path;
    
    // Real application components
    nvvk::Context m_vkContext;
    std::unique_ptr<nvapp::Application> m_app;
    std::unique_ptr<lodclusters::ExternalMemoryManager> m_externalMemory;
    std::shared_ptr<lodclusters::ElementPyBridge> m_pybridge;
    std::shared_ptr<lodclusters::LodClusters> m_lodclusters;
    std::unique_ptr<nvutils::ProfilerManager>   m_profilerManager;
    std::unique_ptr<nvutils::ParameterRegistry> m_parameterRegistry;


    // Threading and synchronization
    std::thread m_renderThread;
    std::atomic<bool> m_running{false};
    std::atomic<bool> m_ready{false};
    std::mutex m_stopMutex;
    std::condition_variable m_stopCondition;
    
    // Shared components for elements
    std::shared_ptr<nvutils::CameraManipulator> m_cameraManipulator;
    
    // Real Vulkan initialization
    void initializeVulkan() {
        printf("Vk2TorchApp: Initializing Vulkan context...\n");
        
        // 1) Initialize Volk
        NVVK_CHECK(volkInitialize());
        
        // Feature structures (same as context_bootstrap.cpp)
        VkPhysicalDeviceMeshShaderFeaturesNV meshNV = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MESH_SHADER_FEATURES_NV};
        VkPhysicalDeviceAccelerationStructureFeaturesKHR accKHR = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ACCELERATION_STRUCTURE_FEATURES_KHR};
        VkPhysicalDeviceRayTracingPipelineFeaturesKHR rayKHR = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_TRACING_PIPELINE_FEATURES_KHR};
        VkPhysicalDeviceRayTracingPositionFetchFeaturesKHR rayPosKHR = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_TRACING_POSITION_FETCH_FEATURES_KHR};
        VkPhysicalDeviceRayQueryFeaturesKHR rayQueryKHR = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_RAY_QUERY_FEATURES_KHR};
        VkPhysicalDeviceClusterAccelerationStructureFeaturesNV clustersNV = {
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_CLUSTER_ACCELERATION_STRUCTURE_FEATURES_NV};
        VkPhysicalDeviceShaderClockFeaturesKHR clockKHR = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_CLOCK_FEATURES_KHR};
        VkPhysicalDeviceShaderAtomicFloatFeaturesEXT atomicFloatFeatures{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_FLOAT_FEATURES_EXT};
        VkPhysicalDeviceFragmentShadingRateFeaturesKHR shadingRateFeatures{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FRAGMENT_SHADING_RATE_FEATURES_KHR};
        VkPhysicalDeviceFragmentShaderBarycentricFeaturesKHR barycentricFeatures{
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FRAGMENT_SHADER_BARYCENTRIC_FEATURES_KHR};

        // Setup context info - headless mode, no surface extensions needed
        nvvk::ContextInitInfo vkSetup{
            .instanceExtensions = {},  // Start empty for headless
            .deviceExtensions   = {},  // No swapchain for headless
            .queues             = {VK_QUEUE_GRAPHICS_BIT, VK_QUEUE_TRANSFER_BIT},
        };
        
        vkSetup.enableValidationLayers = false;  // Disable validation for performance
        vkSetup.forceGPU = -1;  // Auto-select GPU
        
        // Add standard device extensions
        vkSetup.deviceExtensions.push_back({VK_NV_MESH_SHADER_EXTENSION_NAME, &meshNV});
        vkSetup.deviceExtensions.push_back({VK_KHR_DEFERRED_HOST_OPERATIONS_EXTENSION_NAME, nullptr, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME, &accKHR, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_RAY_TRACING_PIPELINE_EXTENSION_NAME, &rayKHR, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_RAY_TRACING_POSITION_FETCH_EXTENSION_NAME, &rayPosKHR, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_RAY_QUERY_EXTENSION_NAME, &rayQueryKHR, false});
        vkSetup.deviceExtensions.push_back({VK_NV_CLUSTER_ACCELERATION_STRUCTURE_EXTENSION_NAME, &clustersNV, false, 2});
        vkSetup.deviceExtensions.push_back({VK_KHR_SHADER_CLOCK_EXTENSION_NAME, &clockKHR, false});
        vkSetup.deviceExtensions.push_back({VK_EXT_SHADER_ATOMIC_FLOAT_EXTENSION_NAME, &atomicFloatFeatures, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME, &shadingRateFeatures, false});
        vkSetup.deviceExtensions.push_back({VK_KHR_FRAGMENT_SHADER_BARYCENTRIC_EXTENSION_NAME, &barycentricFeatures, false});
        vkSetup.deviceExtensions.push_back({VK_NV_SHADER_SUBGROUP_PARTITIONED_EXTENSION_NAME, nullptr, false});

        // Add external memory extensions (needed for CUDA interop)
        printf("Vk2TorchApp: Adding external memory extensions for interop\n");
        for (const auto& ext : lodclusters::ExternalMemoryManager::getRequiredDeviceExtensions()) {
            vkSetup.deviceExtensions.push_back({ext, nullptr, false});
        }

        // 3) Optional: Filter available instance extensions (insurance against any residual extensions)
        auto& inst = vkSetup.instanceExtensions;
        uint32_t cnt = 0;
        vkEnumerateInstanceExtensionProperties(nullptr, &cnt, nullptr);
        std::vector<VkExtensionProperties> props(cnt);
        if (cnt) vkEnumerateInstanceExtensionProperties(nullptr, &cnt, props.data());
        {
            std::vector<const char*> keep;
            for (const char* e : inst) {
                bool found = false;
                for (auto &p: props) if (!strcmp(p.extensionName, e)) { found = true; break; }
                if (found) keep.push_back(e);
                else fprintf(stderr, "[vk2torch] drop unavailable instance ext: %s\n", e);
            }
            inst.swap(keep);
        }
        fprintf(stderr, "[vk2torch] final instanceExtensions count = %zu\n", inst.size());

        m_vkContext.contextInfo = vkSetup;
        
        // 4) Create Instance (with fallback to empty extensions if needed)
        printf("Vk2TorchApp: Creating Vulkan Instance\n");
        VkResult r = m_vkContext.createInstance();
        if (r == VK_ERROR_EXTENSION_NOT_PRESENT) {
            fprintf(stderr, "[vk2torch] EXT_NOT_PRESENT: retry with EMPTY instance extensions\n");
            // Clear extensions and create new Context
            vkSetup.instanceExtensions.clear();
            nvvk::Context newContext;
            newContext.contextInfo = vkSetup;
            NVVK_CHECK(newContext.createInstance());
            m_vkContext = std::move(newContext);
        } else {
            NVVK_CHECK(r);
        }
        
        NVVK_CHECK(m_vkContext.selectPhysicalDevice());
        NVVK_CHECK(m_vkContext.createDevice());
        
        nvvk::DebugUtil::getInstance().init(m_vkContext.getDevice());
        
        printf("Vk2TorchApp: Vulkan context created successfully\n");
    }
    
    void createApplication() {
        printf("Vk2TorchApp: Creating Application with real 3D scene rendering...\n");
        
        // Create shared components
        m_cameraManipulator = std::make_shared<nvutils::CameraManipulator>();
        
        // Create external memory manager for in-process mode
        m_externalMemory = std::make_unique<lodclusters::ExternalMemoryManager>();
        lodclusters::ExternalMemoryConfig extConfig;
        extConfig.enabled = true;
        extConfig.width = m_width;
        extConfig.height = m_height;
        extConfig.format = VK_FORMAT_R32_UINT;  // Packed 24-bit depth in 32-bit
        extConfig.exportDepthFormat = VK_FORMAT_R32_UINT;
        extConfig.pack24In32 = true;
        
        if (!m_externalMemory->initInProcess(m_vkContext.getDevice(), m_vkContext.getPhysicalDevice(), extConfig)) {
            throw std::runtime_error("Failed to initialize external memory manager");
        }
        
        // Create nvapp::Application
        nvapp::ApplicationCreateInfo appInfo;
        appInfo.name = "VK2Torch In-Process - Real 3D Rendering";
        appInfo.headless = true;
        appInfo.headlessFrameCount = 1000000;  // Run indefinitely
        appInfo.windowSize = {static_cast<uint32_t>(m_width), static_cast<uint32_t>(m_height)};
        appInfo.vSync = false;
        appInfo.useMenu = false;
        appInfo.instance = m_vkContext.getInstance();
        appInfo.device = m_vkContext.getDevice();
        appInfo.physicalDevice = m_vkContext.getPhysicalDevice();
        appInfo.queues = m_vkContext.getQueueInfos();
        
        m_app = std::make_unique<nvapp::Application>();
        m_app->init(appInfo);
        
        // Create LodClusters element for real 3D scene rendering
        printf("Vk2TorchApp: Creating LodClusters for real scene rendering...\n");
        lodclusters::LodClusters::Info lodInfo;

        m_profilerManager   = std::make_unique<nvutils::ProfilerManager>();
        m_parameterRegistry = std::make_unique<nvutils::ParameterRegistry>();
        m_cameraManipulator = std::make_shared<nvutils::CameraManipulator>();

        lodInfo.cameraManipulator = m_cameraManipulator;
        lodInfo.profilerManager = m_profilerManager.get();  // No profiler needed for headless
        lodInfo.parameterRegistry = m_parameterRegistry.get();  // Use defaults
        lodInfo.externalMemoryManager = m_externalMemory.get();  // Connect to external memory
        
        m_lodclusters = std::make_shared<lodclusters::LodClusters>(lodInfo);
        m_lodclusters->setSupportsClusters(m_vkContext.hasExtensionEnabled(VK_NV_CLUSTER_ACCELERATION_STRUCTURE_EXTENSION_NAME));
        
        // Create ElementPyBridge for frame synchronization
        m_pybridge = std::make_shared<lodclusters::ElementPyBridge>();
        m_pybridge->setExternalMemoryManager(m_externalMemory.get());
        m_pybridge->setLodClustersElement(m_lodclusters.get());  // Connect to LodClusters!
        
        // Add elements in correct order: PyBridge first (camera control), LodClusters second (rendering)
        m_app->addElement(m_pybridge);
        m_app->addElement(m_lodclusters);
        
        printf("Vk2TorchApp: Real 3D rendering pipeline created successfully\n");
        printf("             - LodClusters will render actual 3D geometry\n");
        printf("             - PyBridge connected for frame synchronization\n");
    }
    
    void loadDefaultScene() {
        printf("Vk2TorchApp: Loading default 3D scene...\n");
        
        // Find bunny.gltf in standard locations (same logic as main.cpp)
        std::filesystem::path scenePath;
        
        if (!m_scene_path.empty()) {
            // User specified a scene path
            scenePath = m_scene_path;
            printf("Vk2TorchApp: Using user-specified scene: %s\n", scenePath.string().c_str());
        } else {
            // Search for default bunny scene
            const std::vector<std::filesystem::path> searchPaths = {
                std::filesystem::absolute(std::filesystem::current_path() / "_downloaded_resources"),
                std::filesystem::absolute(std::filesystem::current_path() / "resources"),
                std::filesystem::absolute(std::filesystem::current_path() / "../resources"),
                std::filesystem::absolute(std::filesystem::current_path() / "downloads")
            };
            
            bool foundBunny = false;
            for (const auto& searchPath : searchPaths) {
                auto fullPath = searchPath / "bunny_v2" / "bunny.gltf";
                if (std::filesystem::exists(fullPath)) {
                    scenePath = fullPath;
                    foundBunny = true;
                    printf("Vk2TorchApp: Found default bunny scene at: %s\n", scenePath.string().c_str());
                    break;
                }
            }
            
            if (!foundBunny) {
                printf("Vk2TorchApp: Warning - bunny.gltf not found, will use empty scene\n");
                printf("             Search paths tried:\n");
                for (const auto& searchPath : searchPaths) {
                    printf("               %s/bunny_v2/bunny.gltf\n", searchPath.string().c_str());
                }
                return;  // Continue without scene - will render empty/test content
            }
        }
        
        // Initialize the scene in LodClusters using public onFileDrop method
        if (m_lodclusters && std::filesystem::exists(scenePath)) {
            // Use onFileDrop which is public and designed for loading scene files
            m_lodclusters->onFileDrop(scenePath);
            printf("Vk2TorchApp: ✅ 3D scene loading initiated: %s\n", scenePath.string().c_str());
        } else {
            printf("Vk2TorchApp: ⚠️ Scene file not found: %s\n", scenePath.string().c_str());
        }
    }
    
    void startRenderThread() {
        printf("Vk2TorchApp: Starting render thread...\n");
        
        m_running = true;
        
        m_renderThread = std::thread([this]() {
            try {
                printf("Vk2TorchApp: Render thread started, running application loop\n");
                
                // Wait for PyBridge to be ready
                if (m_pybridge->waitForReady(10000)) {  // 10 second timeout
                    m_ready = true;
                    printf("Vk2TorchApp: PyBridge ready, application initialized\n");
                    
                    // Now load the default scene after application is fully ready
                    loadDefaultScene();
                } else {
                    printf("Vk2TorchApp: Warning - PyBridge not ready within timeout\n");
                }
                
                // Run the application loop
                m_app->run();
                
                printf("Vk2TorchApp: Application loop exited\n");
            } catch (const std::exception& e) {
                printf("Vk2TorchApp: Render thread exception: %s\n", e.what());
            }
            
            m_running = false;
        });
        
        // Brief wait to ensure thread starts
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        
        printf("Vk2TorchApp: Render thread started successfully\n");
    }
    
    void cleanup() {
        printf("Vk2TorchApp: Cleaning up resources...\n");
        
        // Clean up in reverse order of creation
        if (m_app) {
            m_app->deinit();
            m_app.reset();
        }
        
        // Clean up elements
        m_lodclusters.reset();
        m_pybridge.reset();
        
        if (m_externalMemory) {
            m_externalMemory->deinit();
            m_externalMemory.reset();
        }
        
        m_cameraManipulator.reset();
        
        m_vkContext.deinit();
        
        printf("Vk2TorchApp: Cleanup complete\n");
    }
};

namespace py = pybind11;

PYBIND11_MODULE(vk2torch_ext, m) {
    m.doc() = "VK2Torch Extension - In-process Vulkan to PyTorch integration";

    py::class_<Vk2TorchApp>(m, "Vk2TorchApp")
        .def(py::init<int, int, bool, const std::string&>(),
             "Create Vk2TorchApp instance with headless Application",
             py::arg("width"), py::arg("height"), 
             py::arg("raster") = true, py::arg("scene_path") = "")
        
        // Dimensions and buffer info
        .def("size", &Vk2TorchApp::size,
             "Get render target dimensions as (height, width) tuple")
        
        .def("row_pitch_bytes", &Vk2TorchApp::row_pitch_bytes,
             "Get row pitch in bytes for exported buffers")
        
        // External memory/semaphore export (FD automatically duplicated)
        .def("export_depth_buffer_fd", &Vk2TorchApp::export_depth_buffer_fd,
             "Export depth buffer file descriptor (caller must close)")
        
        .def("export_frame_done_semaphore_fd", &Vk2TorchApp::export_frame_done_semaphore_fd,
             "Export frame done semaphore file descriptor (caller must close)")
        
        // Camera and frame control
        .def("set_camera", &Vk2TorchApp::set_camera,
             "Set camera view and projection matrices with frame number",
             py::arg("frame"), py::arg("view"), py::arg("proj"))
        
        .def("last_signaled_frame", &Vk2TorchApp::last_signaled_frame,
             "Get last signaled frame number from timeline semaphore")
        
        // Lifecycle management
        .def("stop", &Vk2TorchApp::stop,
             "Stop the Application and cleanup resources");

    // Module metadata
    m.attr("__version__") = "1.0.0";
    m.attr("__author__") = "NVIDIA Corporation";
    m.attr("__doc__") = "VK2Torch Extension - In-process Vulkan LOD rendering with zero-copy PyTorch integration";
}