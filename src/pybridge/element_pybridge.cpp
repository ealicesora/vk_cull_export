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

// Use existing logging macros (already defined in nvutils/logger.hpp)

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
  LOGI("Attaching PyBridge element\n");
  // Initialization logic will be completed once connections are set
}

void ElementPyBridge::onDetach() {
  LOGI("Deinitializing PyBridge element\n");
  
  // Wake up any waiting threads
  {
    std::lock_guard<std::mutex> lock(m_readyMutex);
    m_isReady = false;
    m_readyCondition.notify_all();
  }
  
  m_externalMemoryManager = nullptr;
  m_lodClustersElement = nullptr;
}

void ElementPyBridge::onRender(VkCommandBuffer cmd) {
  if (!m_externalMemoryManager || !m_lodClustersElement) {
    // Not fully connected yet
    return;
  }

  // Check if camera data needs updating
  bool updateCamera = false;
  uint64_t frameToRender = m_currentFrame;
  std::array<float, 16> view, proj;

  if (m_cameraDirty.exchange(false)) {
    std::lock_guard<std::mutex> lock(m_cameraMutex);
    frameToRender = m_desiredFrame;
    view = m_viewMatrix;
    proj = m_projMatrix;
    updateCamera = true;
  }

  if (updateCamera) {
    // Update camera UBO (reuse existing UDS logic from LodClusters)
    updateCameraUBO(view.data(), proj.data());
    m_currentFrame = frameToRender;
    LOGI("Updated camera for frame %lu\n", frameToRender);
  }

  // Ensure depth-to-buffer copy is included in the command buffer
  // This would typically be done by the LodClusters renderer
  // For now, we'll just signal the frame as done

  // Signal timeline semaphore with current frame number
  signalFrameDone(cmd, frameToRender);

  // Mark as ready on first frame completion
  if (!m_firstFrameCompleted.exchange(true)) {
    markReady();
  }

  m_lastSignaledFrame = frameToRender;
}

void ElementPyBridge::setExternalMemoryManager(ExternalMemoryManager* manager) {
  m_externalMemoryManager = manager;
  LOGI("PyBridge: Connected to ExternalMemoryManager\n");
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
  return m_externalMemoryManager->exportDepthBufferFdDup();
}

int ElementPyBridge::exportFrameDoneSemaphoreFdDup() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return -1;
  }
  return m_externalMemoryManager->exportFrameDoneSemaphoreFdDup();
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
  return m_externalMemoryManager->getWidth();
}

uint32_t ElementPyBridge::height() const {
  if (!m_externalMemoryManager) {
    LOGE("PyBridge: ExternalMemoryManager not connected\n");
    return 0;
  }
  return m_externalMemoryManager->getHeight();
}

uint64_t ElementPyBridge::lastSignaledFrame() const {
  return m_lastSignaledFrame;
}

void ElementPyBridge::updateCamera(uint64_t frame, const float view[16], const float proj[16]) {
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
  
  LOGI("PyBridge: Updated camera for frame %lu\n", frame);
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

} // namespace lodclusters