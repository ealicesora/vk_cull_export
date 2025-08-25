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

#include "element_pybridge.hpp"
#include "../external_memory.hpp"
#include "../lodclusters.hpp"
#include <nvutils/logger.hpp>
#include <chrono>

namespace lodclusters {

ElementPyBridge::ElementPyBridge() {
  // Initialize view and projection matrices to identity
  m_viewMatrix.fill(0.0f);
  m_projMatrix.fill(0.0f);
  for (int i = 0; i < 4; i++) {
    m_viewMatrix[i * 4 + i] = 1.0f;
    m_projMatrix[i * 4 + i] = 1.0f;
  }
}

ElementPyBridge::~ElementPyBridge() {
  onDetach();
}

void ElementPyBridge::onAttach(nvapp::Application* app) {
  LOGI("PyBridge: Attaching element\n");
  
  // Get Vulkan device from application context
  m_device = app->getDevice();
  if (m_device == VK_NULL_HANDLE) {
    LOGE("PyBridge: Failed to get Vulkan device from application\n");
    return;
  }
  
  // Create camera_ready timeline semaphore
  if (!createCameraReadySemaphore()) {
    LOGE("PyBridge: Failed to create camera ready timeline semaphore\n");
    return;
  }
  
  // Mark as ready immediately for headless mode (don't wait for first onRender)
  markReady();
  
  LOGI("PyBridge: Successfully attached with camera_ready timeline semaphore\n");
}

void ElementPyBridge::onDetach() {
  LOGI("PyBridge: Detaching element\n");
  
  // Wake up any waiting threads
  {
    std::lock_guard<std::mutex> lock(m_readyMutex);
    m_isReady = false;
    m_readyCondition.notify_all();
  }
  
  // Destroy camera ready semaphore
  destroyCameraReadySemaphore();
  
  m_externalMemoryManager = nullptr;
  m_lodClustersElement = nullptr;
  m_device = VK_NULL_HANDLE;
  
  LOGI("PyBridge: Element detached\n");
}

void ElementPyBridge::onRender(VkCommandBuffer cmd) {
  if (!m_externalMemoryManager || !m_lodClustersElement) {
    // Not fully connected yet
    return;
  }

  uint64_t frameToRender = m_currentFrame;
  
  // Wait for camera_ready semaphore with current expected frame
  if (m_cameraReadySemaphore != VK_NULL_HANDLE) {
    if (waitForCameraReady(frameToRender, UINT64_MAX)) {  // ~60fps timeout (16.6ms)
      LOGI("PyBridge: Camera ready for frame %lu\n", frameToRender);
    } else {
      LOGW("PyBridge: Camera ready timeout for frame %lu, proceeding anyway\n", frameToRender);
    }
  }

  // Check if camera data needs updating
  bool updateCamera = false;
  std::array<float, 16> view, proj;

  if (m_cameraDirty.exchange(false)) {
    std::lock_guard<std::mutex> lock(m_cameraMutex);
    frameToRender = m_desiredFrame;
    view = m_viewMatrix;
    proj = m_projMatrix;
    updateCamera = true;
  }

  if (updateCamera) {
    // Update camera UBO
    updateCameraUBO(view.data(), proj.data());
    m_currentFrame = frameToRender;
    LOGI("PyBridge: Updated camera for frame %lu\n", frameToRender);
  }

  // Set coordinated frame value for LodClusters to use in timeline signals
  m_externalMemoryManager->setCurrentFrameValue(frameToRender);
  LOGI("PyBridge: Set coordinated frame value to %lu for LodClusters signal coordination\n", frameToRender);

  // Signal timeline semaphore with current frame number
  signalFrameDone(cmd, frameToRender);

  // Mark as ready on first frame completion (FD export available)
  if (!m_firstFrameCompleted.exchange(true)) {
    markReady();
  }

  m_lastSignaledFrame = frameToRender;
}

void ElementPyBridge::setExternalMemoryManager(ExternalMemoryManager* manager) {
  m_externalMemoryManager = manager;
  LOGI("PyBridge: Connected to ExternalMemoryManager\n");
  
  // Test FD export availability
  if (manager && manager->exportDepthBufferFdDup() >= 0) {
    LOGI("PyBridge: ExternalMemoryManager FD export available\n");
  }
}

void ElementPyBridge::setLodClustersElement(LodClusters* element) {
  m_lodClustersElement = element;
  LOGI("PyBridge: Connected to LodClusters element\n");
}

int ElementPyBridge::exportDepthBufferFdDup() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return -1;
  }
  
  int fd = m_externalMemoryManager->exportDepthBufferFdDup();
  if (fd >= 0) {
    LOGI("PyBridge: Successfully exported depth buffer FD (duplicated): %d\n", fd);
  } else {
    LOGE("PyBridge: Failed to export depth buffer FD\n");
  }
  return fd;
}

int ElementPyBridge::exportFrameDoneSemaphoreFdDup() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return -1;
  }
  
  int fd = m_externalMemoryManager->exportFrameDoneSemaphoreFdDup();
  if (fd >= 0) {
    LOGI("PyBridge: Successfully exported frame done semaphore FD (duplicated): %d\n", fd);
  } else {
    LOGE("PyBridge: Failed to export frame done semaphore FD\n");
  }
  return fd;
}

uint32_t ElementPyBridge::rowPitchBytes() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return 0;
  }
  return m_externalMemoryManager->rowPitchBytes();
}

uint32_t ElementPyBridge::width() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return 0;
  }
  return m_externalMemoryManager->extent().width;
}

uint32_t ElementPyBridge::height() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return 0;
  }
  return m_externalMemoryManager->extent().height;
}

uint64_t ElementPyBridge::lastSignaledFrame() const {
  return m_lastSignaledFrame;
}

void ElementPyBridge::updateCameraAndSignal(uint64_t frame, const float view[16], const float proj[16]) {
  {
    std::lock_guard<std::mutex> lock(m_cameraMutex);
    m_desiredFrame = frame;
    
    // Copy matrices
    for (int i = 0; i < 16; i++) {
      m_viewMatrix[i] = view[i];
      m_projMatrix[i] = proj[i];
    }
  }
  
  // Mark camera as dirty to trigger update in next onRender
  m_cameraDirty = true;
  
  // Signal camera_ready timeline semaphore with frame number (host-side signaling)
  signalCameraReady(frame);
  
  LOGI("PyBridge: Updated camera and signaled ready for frame %lu\n", frame);
}

bool ElementPyBridge::waitForReady(uint32_t timeoutMs) {
  std::unique_lock<std::mutex> lock(m_readyMutex);
  return m_readyCondition.wait_for(lock, std::chrono::milliseconds(timeoutMs), 
                                  [this] { return m_isReady.load(); });
}

void ElementPyBridge::updateCameraUBO(const float view[16], const float proj[16]) {
  // This would typically update the camera uniform buffer
  // For now, we'll delegate to the LodClusters element if available
  if (m_lodClustersElement) {
    // TODO: Call appropriate method on LodClusters to update camera
    // This might require extending the LodClusters interface
    LOGI("PyBridge: Camera UBO update delegated to LodClusters\n");
  }
}

void ElementPyBridge::signalFrameDone(VkCommandBuffer cmd, uint64_t frame) {
  // Add timeline semaphore signal to the command buffer
  // This would typically be done through the ExternalMemoryManager
  if (m_externalMemoryManager) {
    // For now, just log the signal
    // The actual signaling would be done in the command buffer submission
    LOGI("PyBridge: Signaling frame %lu as done\n", frame);
  }
}

void ElementPyBridge::markReady() {
  {
    std::lock_guard<std::mutex> lock(m_readyMutex);
    m_isReady = true;
  }
  m_readyCondition.notify_all();
  LOGI("PyBridge: Marked as ready for FD export\n");
}

// Camera ready timeline semaphore methods

bool ElementPyBridge::createCameraReadySemaphore() {
  if (m_device == VK_NULL_HANDLE) {
    LOGE("PyBridge: Cannot create camera ready semaphore - no device\n");
    return false;
  }
  
  // Create timeline semaphore with initial value 0
  VkSemaphoreTypeCreateInfo timelineCreateInfo{};
  timelineCreateInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO;
  timelineCreateInfo.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
  timelineCreateInfo.initialValue = 0;

  VkSemaphoreCreateInfo createInfo{};
  createInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
  createInfo.pNext = &timelineCreateInfo;

  VkResult result = vkCreateSemaphore(m_device, &createInfo, nullptr, &m_cameraReadySemaphore);
  if (result != VK_SUCCESS) {
    LOGE("PyBridge: Failed to create camera ready timeline semaphore: VkResult=%d\n", static_cast<int>(result));
    return false;
  }

  LOGI("PyBridge: Created camera_ready timeline semaphore successfully\n");
  return true;
}

void ElementPyBridge::destroyCameraReadySemaphore() {
  if (m_cameraReadySemaphore != VK_NULL_HANDLE && m_device != VK_NULL_HANDLE) {
    vkDestroySemaphore(m_device, m_cameraReadySemaphore, nullptr);
    m_cameraReadySemaphore = VK_NULL_HANDLE;
    LOGI("PyBridge: Destroyed camera ready timeline semaphore\n");
  }
}

void ElementPyBridge::signalCameraReady(uint64_t frame) {
  if (m_cameraReadySemaphore == VK_NULL_HANDLE || m_device == VK_NULL_HANDLE) {
    LOGW("PyBridge: Cannot signal camera ready - semaphore not available\n");
    return;
  }

  // Host-side timeline semaphore signaling
  VkSemaphoreSignalInfo signalInfo{};
  signalInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_SIGNAL_INFO;
  signalInfo.semaphore = m_cameraReadySemaphore;
  signalInfo.value = frame;

  VkResult result = vkSignalSemaphore(m_device, &signalInfo);
  if (result != VK_SUCCESS) {
    LOGE("PyBridge: Failed to signal camera ready semaphore for frame %lu: VkResult=%d\n", 
         frame, static_cast<int>(result));
  } else {
    LOGI("PyBridge: Signaled camera_ready=%lu (host-side)\n", frame);
  }
}

bool ElementPyBridge::waitForCameraReady(uint64_t frame, uint64_t timeoutNs) {
  if (m_cameraReadySemaphore == VK_NULL_HANDLE || m_device == VK_NULL_HANDLE) {
    LOGW("PyBridge: Cannot wait for camera ready - semaphore not available\n");
    return false;
  }

  // Host-side timeline semaphore waiting
  VkSemaphoreWaitInfo waitInfo{};
  waitInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO;
  waitInfo.semaphoreCount = 1;
  waitInfo.pSemaphores = &m_cameraReadySemaphore;
  waitInfo.pValues = &frame;

  VkResult result = vkWaitSemaphores(m_device, &waitInfo, timeoutNs);
  if (result == VK_SUCCESS) {
    LOGI("PyBridge: Camera ready wait succeeded for frame %lu\n", frame);
    return true;
  } else if (result == VK_TIMEOUT) {
    LOGW("PyBridge: Camera ready wait timed out for frame %lu\n", frame);
    return false;
  } else {
    LOGE("PyBridge: Camera ready wait failed for frame %lu: VkResult=%d\n", 
         frame, static_cast<int>(result));
    return false;
  }
}

} // namespace lodclusters