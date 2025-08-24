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

#include <nvapp/application.hpp>
#include <vulkan/vulkan.h>
#include <atomic>
#include <array>
#include <mutex>
#include <condition_variable>

namespace lodclusters {

class ExternalMemoryManager;
class LodClusters;

class ElementPyBridge : public nvapp::IAppElement {
public:
  ElementPyBridge();
  virtual ~ElementPyBridge();

  void onAttach(nvapp::Application* app) override;
  void onDetach() override;
  void onRender(VkCommandBuffer cmd) override;

  // Setup connections to other components
  void setExternalMemoryManager(ExternalMemoryManager* manager);
  void setLodClustersElement(LodClusters* element);

  // Python-facing API (called from pybind)
  int exportDepthBufferFdDup() const;
  int exportFrameDoneSemaphoreFdDup() const;
  uint32_t rowPitchBytes() const;
  uint32_t width() const;
  uint32_t height() const;
  uint64_t lastSignaledFrame() const;
  void updateCameraAndSignal(uint64_t frame, const float view[16], const float proj[16]);

  // Wait for resources to be ready for export
  bool waitForReady(uint32_t timeoutMs = 5000);

private:
  // External connections
  ExternalMemoryManager* m_externalMemoryManager = nullptr;
  LodClusters* m_lodClustersElement = nullptr;
  
  // Vulkan context (for camera_ready timeline semaphore)
  VkDevice m_device = VK_NULL_HANDLE;
  VkSemaphore m_cameraReadySemaphore = VK_NULL_HANDLE;

  // Thread-safe camera state
  std::mutex m_cameraMutex;
  std::condition_variable m_cameraCondition;
  std::atomic<uint64_t> m_desiredFrame{1};
  std::array<float, 16> m_viewMatrix{};
  std::array<float, 16> m_projMatrix{};
  std::atomic<bool> m_cameraDirty{false};

  // Ready state tracking
  std::mutex m_readyMutex;
  std::condition_variable m_readyCondition;
  std::atomic<bool> m_isReady{false};
  std::atomic<bool> m_firstFrameCompleted{false};

  // Frame tracking
  std::atomic<uint64_t> m_currentFrame{1};
  std::atomic<uint64_t> m_lastSignaledFrame{0};

  // Helper methods
  void updateCameraUBO(const float view[16], const float proj[16]);
  void signalFrameDone(VkCommandBuffer cmd, uint64_t frame);
  void markReady();
  
  // Camera ready timeline semaphore methods
  bool createCameraReadySemaphore();
  void destroyCameraReadySemaphore();
  void signalCameraReady(uint64_t frame);
  bool waitForCameraReady(uint64_t frame, uint64_t timeoutNs = 1000000000ULL);  // 1 second default
};

} // namespace lodclusters