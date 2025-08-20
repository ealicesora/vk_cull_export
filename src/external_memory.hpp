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

#pragma once

#include <vulkan/vulkan.h>
#include <string>
#include <vector>
#include <memory>

#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#endif

namespace lodclusters {

struct ExternalMemoryConfig {
  bool enabled = false;
  std::string udsPath = "/tmp/vk2torch.sock";
  bool offscreen = false;
  uint32_t width = 1920;
  uint32_t height = 1080;
  VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
};

class ExternalMemoryManager {
public:
  ExternalMemoryManager() = default;
  ~ExternalMemoryManager();

  bool init(VkDevice device, VkPhysicalDevice physicalDevice, const ExternalMemoryConfig& config);
  void deinit();

  // Create exportable resources
  bool createExportableBuffer(VkDeviceSize size, VkBufferUsageFlags usage, 
                              VkBuffer* buffer, VkDeviceMemory* memory, int* fd, VkDeviceSize* actualSize = nullptr);
  bool createExportableTimelineSemaphore(VkSemaphore* semaphore, uint64_t initialValue, int* fd);
  
  // Export existing resources
  int exportMemoryFd(VkDeviceMemory memory);
  int exportSemaphoreFd(VkSemaphore semaphore);

  // UDS communication
  bool setupUDS();
  bool acceptClient();
  bool sendHandshakeInfo();
  bool sendFds(const std::vector<int>& fds);

  // Frame synchronization
  bool waitForCameraReady(uint64_t frameNumber);
  bool signalFrameDone(uint64_t frameNumber);

  // Getters
  VkBuffer getCameraBuffer() const { return m_cameraBuffer; }
  VkBuffer getColorReadbackBuffer() const { return m_colorReadbackBuffer; }
  VkSemaphore getCameraSemaphore() const { return m_cameraSemaphore; }
  VkSemaphore getFrameDoneSemaphore() const { return m_frameDoneSemaphore; }
  
  bool isConnected() const;  // Check if client is still connected
  uint32_t getWidth() const { return m_config.width; }
  uint32_t getHeight() const { return m_config.height; }
  VkFormat getFormat() const { return m_config.format; }

  // Vulkan device extensions required
  static std::vector<const char*> getRequiredDeviceExtensions() {
    return {
      VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME,
      VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
      VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME,
      VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
      VK_KHR_TIMELINE_SEMAPHORE_EXTENSION_NAME
    };
  }

private:
  VkDevice m_device = VK_NULL_HANDLE;
  VkPhysicalDevice m_physicalDevice = VK_NULL_HANDLE;
  ExternalMemoryConfig m_config;

  // Exportable resources
  VkBuffer m_cameraBuffer = VK_NULL_HANDLE;
  VkDeviceMemory m_cameraMemory = VK_NULL_HANDLE;
  
  VkBuffer m_colorReadbackBuffer = VK_NULL_HANDLE;
  VkDeviceMemory m_colorReadbackMemory = VK_NULL_HANDLE;
  
  VkSemaphore m_cameraSemaphore = VK_NULL_HANDLE;
  VkSemaphore m_frameDoneSemaphore = VK_NULL_HANDLE;

  // UDS socket
  int m_serverSocket = -1;
  int m_clientSocket = -1;

  // Actual allocated sizes (may be larger than requested due to alignment)
  VkDeviceSize m_cameraBufferSize = 0;
  VkDeviceSize m_colorBufferSize = 0;

  // Helper functions
  uint32_t findMemoryType(uint32_t typeFilter, VkMemoryPropertyFlags properties);
  bool checkExtensionSupport(const char* extensionName);
};

} // namespace lodclusters