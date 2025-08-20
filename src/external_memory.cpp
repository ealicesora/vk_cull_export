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

#include <volk.h>  // Must be included before any Vulkan headers for function loading
#include "external_memory.hpp"
#include <cstdio>
#include <cstring>

// Simple logging macros
#define LOGI(...) printf("[INFO] " __VA_ARGS__)
#define LOGE(...) printf("[ERROR] " __VA_ARGS__)

// Size of FrameConstants structure from shaderio.h
// We define this manually to avoid including the shader headers
static const size_t FRAME_CONSTANTS_SIZE = sizeof(float) * (16 * 7 + 4 * 9 + 3 * 2 + 2 * 4 + 1 * 4 + 20);

#ifndef _WIN32
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>
#include <errno.h>
#include <fcntl.h>
#endif

// Use simple JSON implementation instead of nlohmann
#include <sstream>
#include <iomanip>

namespace lodclusters {

ExternalMemoryManager::~ExternalMemoryManager() {
  deinit();
}

bool ExternalMemoryManager::init(VkDevice device, VkPhysicalDevice physicalDevice, const ExternalMemoryConfig& config) {
  m_device = device;
  m_physicalDevice = physicalDevice;
  m_config = config;
  
  if (!m_config.enabled) {
    return true;
  }

  LOGI("Initializing External Memory Manager with UDS: %s\n", m_config.udsPath.c_str());

  // Check if required extensions are supported
  for (const auto& ext : getRequiredDeviceExtensions()) {
    if (!checkExtensionSupport(ext)) {
      LOGE("Required extension %s not supported\n", ext);
      return false;
    }
  }

  // Create exportable buffers and semaphores
  VkDeviceSize cameraBufferSize = FRAME_CONSTANTS_SIZE;
  VkDeviceSize colorBufferSize = m_config.width * m_config.height * 4; // R8G8B8A8_UNORM

  LOGI("Creating camera buffer (size: %zu bytes)\n", cameraBufferSize);
  int cameraFd = -1;
  if (!createExportableBuffer(cameraBufferSize, 
                              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                              &m_cameraBuffer, &m_cameraMemory, &cameraFd, &m_cameraBufferSize)) {
    LOGE("Failed to create camera buffer\n");
    return false;
  }
  LOGI("  Actual allocated size: %zu bytes\n", m_cameraBufferSize);

  LOGI("Creating color readback buffer (size: %zu bytes)\n", colorBufferSize);
  int colorFd = -1;
  if (!createExportableBuffer(colorBufferSize,
                              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                              &m_colorReadbackBuffer, &m_colorReadbackMemory, &colorFd, &m_colorBufferSize)) {
    LOGE("Failed to create color readback buffer\n");
    return false;
  }
  LOGI("  Actual allocated size: %zu bytes\n", m_colorBufferSize);

  LOGI("Creating timeline semaphores\n");
  int camSemFd = -1, doneSemFd = -1;
  if (!createExportableTimelineSemaphore(&m_cameraSemaphore, 0, &camSemFd) ||
      !createExportableTimelineSemaphore(&m_frameDoneSemaphore, 0, &doneSemFd)) {
    LOGE("Failed to create timeline semaphores\n");
    return false;
  }

  // Setup UDS server
  if (!setupUDS()) {
    LOGE("Failed to setup UDS server\n");
    return false;
  }

  LOGI("External Memory Manager initialized successfully\n");
  return true;
}

void ExternalMemoryManager::deinit() {
  if (m_device == VK_NULL_HANDLE) return;

  // Close client socket
  if (m_clientSocket >= 0) {
    close(m_clientSocket);
    m_clientSocket = -1;
  }

  // Close server socket
  if (m_serverSocket >= 0) {
    close(m_serverSocket);
    m_serverSocket = -1;
    // Remove socket file
    unlink(m_config.udsPath.c_str());
  }

  // Destroy Vulkan resources
  if (m_cameraBuffer != VK_NULL_HANDLE) {
    vkDestroyBuffer(m_device, m_cameraBuffer, nullptr);
    m_cameraBuffer = VK_NULL_HANDLE;
  }
  if (m_cameraMemory != VK_NULL_HANDLE) {
    vkFreeMemory(m_device, m_cameraMemory, nullptr);
    m_cameraMemory = VK_NULL_HANDLE;
  }
  if (m_colorReadbackBuffer != VK_NULL_HANDLE) {
    vkDestroyBuffer(m_device, m_colorReadbackBuffer, nullptr);
    m_colorReadbackBuffer = VK_NULL_HANDLE;
  }
  if (m_colorReadbackMemory != VK_NULL_HANDLE) {
    vkFreeMemory(m_device, m_colorReadbackMemory, nullptr);
    m_colorReadbackMemory = VK_NULL_HANDLE;
  }
  if (m_cameraSemaphore != VK_NULL_HANDLE) {
    vkDestroySemaphore(m_device, m_cameraSemaphore, nullptr);
    m_cameraSemaphore = VK_NULL_HANDLE;
  }
  if (m_frameDoneSemaphore != VK_NULL_HANDLE) {
    vkDestroySemaphore(m_device, m_frameDoneSemaphore, nullptr);
    m_frameDoneSemaphore = VK_NULL_HANDLE;
  }

  m_device = VK_NULL_HANDLE;
  m_physicalDevice = VK_NULL_HANDLE;
}

bool ExternalMemoryManager::createExportableBuffer(VkDeviceSize size, VkBufferUsageFlags usage,
                                                   VkBuffer* buffer, VkDeviceMemory* memory, int* fd, VkDeviceSize* actualSize) {
#ifdef _WIN32
  LOGE("External memory not supported on Windows\n");
  return false;
#else
  // Create buffer with external memory
  VkExternalMemoryBufferCreateInfo extBuf{VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO};
  extBuf.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

  VkBufferCreateInfo bufferInfo{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
  bufferInfo.pNext = &extBuf;
  bufferInfo.size = size;
  bufferInfo.usage = usage;
  bufferInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

  VkResult result = vkCreateBuffer(m_device, &bufferInfo, nullptr, buffer);
  if (result != VK_SUCCESS) {
    LOGE("Failed to create exportable buffer: %d\n", result);
    return false;
  }

  // Get memory requirements
  VkMemoryRequirements memReq;
  vkGetBufferMemoryRequirements(m_device, *buffer, &memReq);

  // Check if this usage+handleType combination supports export
  VkPhysicalDeviceExternalBufferInfo ebi{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO};
  ebi.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
  ebi.usage = usage;

  VkExternalBufferProperties ebp{VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES};
  vkGetPhysicalDeviceExternalBufferProperties(m_physicalDevice, &ebi, &ebp);

  if (!(ebp.externalMemoryProperties.externalMemoryFeatures & VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT)) {
    LOGE("ERROR: This buffer usage (0x%X) with OPAQUE_FD handle type is not exportable on this platform\n", usage);
    LOGE("  External memory features: 0x%X\n", ebp.externalMemoryProperties.externalMemoryFeatures);
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }

  // Also check if it's compatible with the memory types we can allocate from
  if (!(ebp.externalMemoryProperties.compatibleHandleTypes & VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT)) {
    LOGE("ERROR: OPAQUE_FD handle type not compatible with this buffer configuration\n");
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }

  LOGI("External buffer export check passed (features: 0x%X)\n", ebp.externalMemoryProperties.externalMemoryFeatures);

  // Return actual allocated size if requested
  if (actualSize) {
    *actualSize = memReq.size;
  }

  // Allocate device-local memory with export capability
  VkExportMemoryAllocateInfo exportAlloc{VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO};
  exportAlloc.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

  VkMemoryAllocateInfo allocInfo{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
  allocInfo.pNext = &exportAlloc;
  allocInfo.allocationSize = memReq.size;
  
  // Use the enhanced memory type finder that considers export capability
  uint32_t memTypeIndex = findMemoryTypeWithExport(memReq.memoryTypeBits, 
                                                    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                                                    VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT);
  
  if (memTypeIndex == UINT32_MAX) {
    LOGE("Failed to find memory type that supports external export\n");
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }
  
  allocInfo.memoryTypeIndex = memTypeIndex;
  LOGI("Using memory type index %u for external buffer\n", memTypeIndex);

  result = vkAllocateMemory(m_device, &allocInfo, nullptr, memory);
  if (result != VK_SUCCESS) {
    LOGE("Failed to allocate exportable memory: %d\n", result);
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }

  // Bind buffer to memory
  result = vkBindBufferMemory(m_device, *buffer, *memory, 0);
  if (result != VK_SUCCESS) {
    LOGE("Failed to bind buffer memory: %d\n", result);
    vkFreeMemory(m_device, *memory, nullptr);
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }

  // Export memory FD
  *fd = exportMemoryFd(*memory);
  if (*fd < 0) {
    LOGE("Failed to export memory FD\n");
    vkFreeMemory(m_device, *memory, nullptr);
    vkDestroyBuffer(m_device, *buffer, nullptr);
    return false;
  }

  return true;
#endif
}

bool ExternalMemoryManager::createExportableTimelineSemaphore(VkSemaphore* semaphore, uint64_t initialValue, int* fd) {
#ifdef _WIN32
  LOGE("External semaphores not supported on Windows\n");
  return false;
#else
  VkSemaphoreTypeCreateInfo typeInfo{VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO};
  typeInfo.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
  typeInfo.initialValue = initialValue;

  VkExportSemaphoreCreateInfo exportSem{VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO};
  exportSem.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;
  typeInfo.pNext = &exportSem;

  VkSemaphoreCreateInfo semInfo{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
  semInfo.pNext = &typeInfo;

  VkResult result = vkCreateSemaphore(m_device, &semInfo, nullptr, semaphore);
  if (result != VK_SUCCESS) {
    LOGE("Failed to create exportable timeline semaphore: %d\n", result);
    return false;
  }

  *fd = exportSemaphoreFd(*semaphore);
  if (*fd < 0) {
    LOGE("Failed to export semaphore FD\n");
    vkDestroySemaphore(m_device, *semaphore, nullptr);
    return false;
  }

  return true;
#endif
}

int ExternalMemoryManager::exportMemoryFd(VkDeviceMemory memory) {
#ifdef _WIN32
  return -1;
#else
  int fd = -1;
  VkMemoryGetFdInfoKHR getFdInfo{VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR};
  getFdInfo.memory = memory;
  getFdInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

  PFN_vkGetMemoryFdKHR vkGetMemoryFdKHR = 
    (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(m_device, "vkGetMemoryFdKHR");
  if (!vkGetMemoryFdKHR) {
    LOGE("vkGetMemoryFdKHR not available\n");
    return -1;
  }

  VkResult result = vkGetMemoryFdKHR(m_device, &getFdInfo, &fd);
  if (result != VK_SUCCESS) {
    LOGE("Failed to get memory FD: %d\n", result);
    return -1;
  }

  return fd;
#endif
}

int ExternalMemoryManager::exportSemaphoreFd(VkSemaphore semaphore) {
#ifdef _WIN32
  return -1;
#else
  int fd = -1;
  VkSemaphoreGetFdInfoKHR getFdInfo{VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR};
  getFdInfo.semaphore = semaphore;
  getFdInfo.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;

  PFN_vkGetSemaphoreFdKHR vkGetSemaphoreFdKHR = 
    (PFN_vkGetSemaphoreFdKHR)vkGetDeviceProcAddr(m_device, "vkGetSemaphoreFdKHR");
  if (!vkGetSemaphoreFdKHR) {
    LOGE("vkGetSemaphoreFdKHR not available\n");
    return -1;
  }

  VkResult result = vkGetSemaphoreFdKHR(m_device, &getFdInfo, &fd);
  if (result != VK_SUCCESS) {
    LOGE("Failed to get semaphore FD: %d\n", result);
    return -1;
  }

  return fd;
#endif
}

bool ExternalMemoryManager::setupUDS() {
#ifdef _WIN32
  LOGE("UDS not supported on Windows\n");
  return false;
#else
  m_serverSocket = socket(AF_UNIX, SOCK_STREAM, 0);
  if (m_serverSocket < 0) {
    LOGE("Failed to create UDS socket\n");
    return false;
  }

  // Remove existing socket file
  unlink(m_config.udsPath.c_str());

  struct sockaddr_un addr;
  memset(&addr, 0, sizeof(addr));
  addr.sun_family = AF_UNIX;
  strncpy(addr.sun_path, m_config.udsPath.c_str(), sizeof(addr.sun_path) - 1);

  if (bind(m_serverSocket, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
    LOGE("Failed to bind UDS socket to %s\n", m_config.udsPath.c_str());
    close(m_serverSocket);
    m_serverSocket = -1;
    return false;
  }

  if (listen(m_serverSocket, 1) < 0) {
    LOGE("Failed to listen on UDS socket\n");
    close(m_serverSocket);
    m_serverSocket = -1;
    return false;
  }

  LOGI("UDS server listening on %s\n", m_config.udsPath.c_str());
  return true;
#endif
}

bool ExternalMemoryManager::acceptClient() {
#ifdef _WIN32
  return false;
#else
  if (m_serverSocket < 0) {
    LOGE("UDS server not initialized\n");
    return false;
  }

  LOGI("Waiting for Python client connection...\n");
  m_clientSocket = accept(m_serverSocket, nullptr, nullptr);
  if (m_clientSocket < 0) {
    LOGE("Failed to accept client connection\n");
    return false;
  }

  LOGI("Python client connected\n");
  return sendHandshakeInfo();
#endif
}

bool ExternalMemoryManager::sendHandshakeInfo() {
#ifdef _WIN32
  return false;
#else
  // Get device UUID for GPU matching
  VkPhysicalDeviceIDProperties idProps{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES};
  VkPhysicalDeviceProperties2 props2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
  props2.pNext = &idProps;
  vkGetPhysicalDeviceProperties2(m_physicalDevice, &props2);
  
  // Convert UUID to hex string (16 bytes -> 32 hex chars)
  std::ostringstream uuidHex;
  uuidHex << std::hex << std::setfill('0');
  for (int i = 0; i < VK_UUID_SIZE; i++) {
    uuidHex << std::setw(2) << static_cast<unsigned int>(idProps.deviceUUID[i]);
  }
  
  LOGI("Vulkan device UUID: %s\n", uuidHex.str().c_str());
  
  // Create simple JSON manually
  std::ostringstream json;
  json << "{"
       << "\"w\":" << m_config.width << ","
       << "\"h\":" << m_config.height << ","
       << "\"format\":\"R8G8B8A8_UNORM\","
       << "\"color_readback_bytes\":" << m_colorBufferSize << ","
       << "\"row_pitch\":" << (m_config.width * 4) << ","
       << "\"cam_bytes\":" << m_cameraBufferSize << ","
       << "\"vk_uuid\":\"" << uuidHex.str() << "\","
       << "\"sem_init\":{\"cam\":0,\"done\":0}"
       << "}";

  std::string jsonStr = json.str();
  
  // Send JSON header first
  uint32_t jsonSize = jsonStr.size();
  if (send(m_clientSocket, &jsonSize, sizeof(jsonSize), 0) != sizeof(jsonSize)) {
    LOGE("Failed to send JSON size\n");
    return false;
  }
  
  if (send(m_clientSocket, jsonStr.c_str(), jsonSize, 0) != (ssize_t)jsonSize) {
    LOGE("Failed to send JSON data\n");
    return false;
  }

  // Export FDs and send them
  std::vector<int> fds;
  int camFd = exportMemoryFd(m_cameraMemory);
  int colorFd = exportMemoryFd(m_colorReadbackMemory);
  int camSemFd = exportSemaphoreFd(m_cameraSemaphore);
  int doneSemFd = exportSemaphoreFd(m_frameDoneSemaphore);

  if (camFd < 0 || colorFd < 0 || camSemFd < 0 || doneSemFd < 0) {
    LOGE("Failed to export FDs for handshake\n");
    return false;
  }

  // Log the FDs being sent from Vulkan side
  fprintf(stdout, "=== VULKAN SIDE: Exporting FDs ===\n");
  fprintf(stdout, "  Camera Memory FD:    %d\n", camFd);
  fprintf(stdout, "  Color Memory FD:     %d\n", colorFd);
  fprintf(stdout, "  Camera Semaphore FD: %d\n", camSemFd);
  fprintf(stdout, "  Done Semaphore FD:   %d\n", doneSemFd);
  fprintf(stdout, "===================================\n");
  fflush(stdout);
  
  LOGI("=== VULKAN SIDE: Exporting FDs ===\n");
  LOGI("  Camera Memory FD:    %d\n", camFd);
  LOGI("  Color Memory FD:     %d\n", colorFd);
  LOGI("  Camera Semaphore FD: %d\n", camSemFd);
  LOGI("  Done Semaphore FD:   %d\n", doneSemFd);
  LOGI("===================================\n");

  fds.push_back(camFd);
  fds.push_back(colorFd);
  fds.push_back(camSemFd);
  fds.push_back(doneSemFd);

  bool success = sendFds(fds);
  
  // Close local copies of FDs
  for (int fd : fds) {
    close(fd);
  }

  if (!success) {
    LOGE("Failed to send FDs via SCM_RIGHTS\n");
    return false;
  }

  LOGI("Handshake completed successfully\n");
  return true;
#endif
}

bool ExternalMemoryManager::sendFds(const std::vector<int>& fds) {
#ifdef _WIN32
  return false;
#else
  struct msghdr msg = {};
  struct iovec iov = {};
  char dummy = 1;
  
  // Set up dummy data
  iov.iov_base = &dummy;
  iov.iov_len = 1;
  msg.msg_iov = &iov;
  msg.msg_iovlen = 1;

  // Set up control message for FDs
  size_t cmsgSize = CMSG_SPACE(sizeof(int) * fds.size());
  char* cmsgBuf = new char[cmsgSize];
  memset(cmsgBuf, 0, cmsgSize);
  
  msg.msg_control = cmsgBuf;
  msg.msg_controllen = cmsgSize;

  struct cmsghdr* cmsg = CMSG_FIRSTHDR(&msg);
  cmsg->cmsg_level = SOL_SOCKET;
  cmsg->cmsg_type = SCM_RIGHTS;
  cmsg->cmsg_len = CMSG_LEN(sizeof(int) * fds.size());
  memcpy(CMSG_DATA(cmsg), fds.data(), sizeof(int) * fds.size());

  ssize_t sent = sendmsg(m_clientSocket, &msg, 0);
  delete[] cmsgBuf;

  if (sent < 0) {
    LOGE("Failed to send FDs via SCM_RIGHTS: %s\n", strerror(errno));
    return false;
  }

  return true;
#endif
}

bool ExternalMemoryManager::waitForCameraReady(uint64_t frameNumber) {
#ifdef _WIN32
  return false;
#else
  if (!isConnected()) {
    return false;
  }

  VkSemaphoreWaitInfo waitInfo{VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO};
  waitInfo.semaphoreCount = 1;
  waitInfo.pSemaphores = &m_cameraSemaphore;
  waitInfo.pValues = &frameNumber;

  VkResult result = vkWaitSemaphores(m_device, &waitInfo, UINT64_MAX);
  if (result != VK_SUCCESS) {
    LOGE("Failed to wait for camera semaphore (frame %lu): %d\n", frameNumber, result);
    return false;
  }

  return true;
#endif
}

bool ExternalMemoryManager::signalFrameDone(uint64_t frameNumber) {
#ifdef _WIN32
  return false;
#else
  if (!isConnected()) {
    return false;
  }

  VkTimelineSemaphoreSubmitInfo timelineInfo{VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO};
  timelineInfo.signalSemaphoreValueCount = 1;
  timelineInfo.pSignalSemaphoreValues = &frameNumber;

  VkSubmitInfo submitInfo{VK_STRUCTURE_TYPE_SUBMIT_INFO};
  submitInfo.pNext = &timelineInfo;
  submitInfo.signalSemaphoreCount = 1;
  submitInfo.pSignalSemaphores = &m_frameDoneSemaphore;

  // Need to get queue from somewhere - for now use VK_NULL_HANDLE
  // This needs to be passed in or stored
  VkQueue queue = VK_NULL_HANDLE; // TODO: Get graphics queue
  VkResult result = vkQueueSubmit(queue, 1, &submitInfo, VK_NULL_HANDLE);
  if (result != VK_SUCCESS) {
    LOGE("Failed to signal frame done semaphore (frame %lu): %d\n", frameNumber, result);
    return false;
  }

  return true;
#endif
}

uint32_t ExternalMemoryManager::findMemoryType(uint32_t typeFilter, VkMemoryPropertyFlags properties) {
  VkPhysicalDeviceMemoryProperties memProps;
  vkGetPhysicalDeviceMemoryProperties(m_physicalDevice, &memProps);

  for (uint32_t i = 0; i < memProps.memoryTypeCount; i++) {
    if ((typeFilter & (1 << i)) && (memProps.memoryTypes[i].propertyFlags & properties) == properties) {
      return i;
    }
  }

  LOGE("Failed to find suitable memory type\n");
  return 0; // This should not happen with device-local memory
}

uint32_t ExternalMemoryManager::findMemoryTypeWithExport(uint32_t typeFilter, VkMemoryPropertyFlags properties, 
                                                         VkExternalMemoryHandleTypeFlagBits handleType) {
  VkPhysicalDeviceMemoryProperties memProps;
  vkGetPhysicalDeviceMemoryProperties(m_physicalDevice, &memProps);

  for (uint32_t i = 0; i < memProps.memoryTypeCount; i++) {
    if ((typeFilter & (1 << i)) && (memProps.memoryTypes[i].propertyFlags & properties) == properties) {
      // For now, we trust that if the buffer export check passed,
      // and this memory type matches our requirements, it should work.
      // A more thorough check would require querying each memory type's export capabilities,
      // but Vulkan doesn't provide a direct API for that on a per-memory-type basis.
      
      LOGI("Found memory type %u with properties 0x%X for external export\n", i, properties);
      return i;
    }
  }

  LOGE("Failed to find suitable memory type with export capability\n");
  return UINT32_MAX; // Invalid memory type index
}

bool ExternalMemoryManager::checkExtensionSupport(const char* extensionName) {
  uint32_t extensionCount;
  vkEnumerateDeviceExtensionProperties(m_physicalDevice, nullptr, &extensionCount, nullptr);
  
  std::vector<VkExtensionProperties> availableExtensions(extensionCount);
  vkEnumerateDeviceExtensionProperties(m_physicalDevice, nullptr, &extensionCount, availableExtensions.data());

  for (const auto& extension : availableExtensions) {
    if (strcmp(extension.extensionName, extensionName) == 0) {
      return true;
    }
  }
  return false;
}

bool ExternalMemoryManager::isConnected() const {
#ifdef _WIN32
  return false;
#else
  if (m_clientSocket < 0) {
    return false;
  }
  
  // Check if socket is still connected by attempting to peek at incoming data
  char buffer;
  int result = recv(m_clientSocket, &buffer, 1, MSG_PEEK | MSG_DONTWAIT);
  
  if (result == 0) {
    // Connection closed by peer
    return false;
  } else if (result < 0) {
    // Check for error
    if (errno == EAGAIN || errno == EWOULDBLOCK) {
      // No data available but connection is still alive
      return true;
    } else {
      // Some other error, connection is likely dead
      return false;
    }
  }
  
  // Data available, connection is alive
  return true;
#endif
}

} // namespace lodclusters