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

#include <fmt/format.h>
#include <nvutils/file_operations.hpp>
#include <nvgui/camera.hpp>

#include "lodclusters.hpp"
#if USE_DLSS
#include "../shaders/dlss_util.h"
#endif

bool g_verbose = false;



// 假设：externalMemoryManager 里有这些信息
//  - VkBuffer colorBuffer;              // 外部(导出)线性buffer
//  - uint32_t rowPitchBytes;            // 握手传来的 row_pitch
//  - uint32_t bytesPerPixel = 4;        // RGBA8
//  - 保证 buffer 的 size >= rowPitchBytes * height
//  - buffer 创建时带 VK_BUFFER_USAGE_TRANSFER_DST_BIT

void recordCopyToExternal(VkCommandBuffer cmd,
                          VkImage srcImage,
                          VkImageLayout srcOldLayout, // 实际当前布局
                          uint32_t width, uint32_t height,
                          VkBuffer dstBuffer,
                          uint32_t rowPitchBytes)
{
  // 1) image: COLOR_ATTACHMENT_OPTIMAL -> TRANSFER_SRC_OPTIMAL
  VkImageMemoryBarrier2 pre{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
  pre.srcStageMask  = VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT;
  pre.srcAccessMask = VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT;
  pre.dstStageMask  = VK_PIPELINE_STAGE_2_TRANSFER_BIT;
  pre.dstAccessMask = VK_ACCESS_2_TRANSFER_READ_BIT;
  pre.oldLayout     = srcOldLayout;                        // ⚠️ 用真实布局
  pre.newLayout     = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
  pre.image         = srcImage;
  pre.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};

  VkDependencyInfo dep{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
  dep.imageMemoryBarrierCount = 1;
  dep.pImageMemoryBarriers    = &pre;
  vkCmdPipelineBarrier2(cmd, &dep);

  // 2) copy: image -> buffer（行距用“像素”，不是字节）
  VkBufferImageCopy region{};
  region.bufferOffset      = 0;                       // 4 字节对齐即可
  region.bufferRowLength   = rowPitchBytes / 4;       // RGBA8 => /4
  region.bufferImageHeight = 0;                       // 按 imageExtent
  region.imageSubresource  = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
  region.imageOffset       = {0, 0, 0};
  region.imageExtent       = {width, height, 1};
  vkCmdCopyImageToBuffer(cmd, srcImage,
                         VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                         dstBuffer, 1, &region);

  // 3) （可选）把 image 转回后续需要的布局（如果后面还要用）
  // VkImageMemoryBarrier2 post = ... old=TRANSFER_SRC_OPTIMAL -> new=COLOR_ATTACHMENT_OPTIMAL / SHADER_READ_ONLY_OPTIMAL
  // vkCmdPipelineBarrier2(cmd, &dep2);

  // 说明：buffer 侧不需要另外 barrier；跨 API 的可见性由 submit 时的 timeline semaphore 保证。
}



namespace lodclusters {

LodClusters::LodClusters(const Info& info)
    : m_info(info)
{
  nvutils::ProfilerTimeline::CreateInfo createInfo;
  createInfo.name = "graphics";

  m_profilerTimeline = m_info.profilerManager->createTimeline(createInfo);

  m_info.parameterRegistry->add({"scene"}, {".gltf", ".glb"}, &m_sceneFilePath);
  m_info.parameterRegistry->add({"renderer"}, (int*)&m_tweak.renderer);
  m_info.parameterRegistry->add({"verbose"}, &g_verbose, true);
  m_info.parameterRegistry->add({"resetstats"}, &m_tweak.autoResetTimers);
  m_info.parameterRegistry->add({"supersample"}, &m_tweak.supersample);
  m_info.parameterRegistry->add({"debugui"}, &m_showDebugUI);

  m_info.parameterRegistry->add({"dumpspirv", "dumps compiled spirv into working directory"}, &m_resources.m_dumpSpirv);

  m_info.parameterRegistry->add({"streaming"}, &m_tweak.useStreaming);
  m_info.parameterRegistry->add({"clasallocator"}, &m_streamingConfig.usePersistentClasAllocator);
  m_info.parameterRegistry->add({"gridcopies"}, &m_sceneGridConfig.numCopies);
  m_info.parameterRegistry->add({"gridconfig"}, &m_sceneGridConfig.gridBits);
  m_info.parameterRegistry->add({"gridunique"}, &m_sceneGridConfig.uniqueGeometriesForCopies);
  m_info.parameterRegistry->add({"clusterconfig"}, (int*)&m_tweak.clusterConfig);
  m_info.parameterRegistry->add({"loderror"}, &m_frameConfig.lodPixelError);
  m_info.parameterRegistry->add({"cullederrorscale"}, &m_frameConfig.culledErrorScale);
  m_info.parameterRegistry->add({"culling"}, &m_rendererConfig.useCulling);
#if USE_DLSS
  m_info.parameterRegistry->add({"dlss"}, &m_rendererConfig.useDlss);
  m_info.parameterRegistry->add({"dlssquality"}, (int*)&m_rendererConfig.dlssQuality);
#endif
  m_info.parameterRegistry->add({"blassharing"}, &m_rendererConfig.useBlasSharing);
  m_info.parameterRegistry->add({"separategroups"}, &m_rendererConfig.useSeparateGroups);
  m_info.parameterRegistry->add({"sharingmininstances"}, &m_frameConfig.sharingMinInstances);
  m_info.parameterRegistry->add({"sharingpushculled"}, &m_frameConfig.sharingPushCulled);
  m_info.parameterRegistry->add({"sharingminlevel"}, &m_frameConfig.sharingMinLevel);
  m_info.parameterRegistry->add({"sharingtolerancelevel"}, &m_frameConfig.sharingToleranceLevel);
  m_info.parameterRegistry->add({"instancesorting"}, &m_rendererConfig.useSorting);
  m_info.parameterRegistry->add({"renderclusterbits"}, &m_rendererConfig.numRenderClusterBits);
  m_info.parameterRegistry->add({"rendertraversalbits"}, &m_rendererConfig.numTraversalTaskBits);
  m_info.parameterRegistry->add({"visualize"}, &m_frameConfig.visualize);
  m_info.parameterRegistry->add({"renderstats"}, &m_rendererConfig.useRenderStats);
  m_info.parameterRegistry->add({"hbao"}, &m_tweak.hbaoActive);
  m_info.parameterRegistry->add({"facetshading"}, &m_tweak.facetShading);
  m_info.parameterRegistry->add({"flipwinding"}, &m_rendererConfig.flipWinding);
  m_info.parameterRegistry->add({"twosided"}, &m_rendererConfig.twoSided);
  m_info.parameterRegistry->add({"autosharing", "automatically set blas sharing based on scene's instancing usage. default true"},
                                &m_tweak.autoSharing);
  m_info.parameterRegistry->add({"autosavecache", "automatically store cache file for loaded scene. default true"},
                                &m_sceneConfig.autoSaveCache);
  m_info.parameterRegistry->add({"autoloadcache", "automatically load cache file if found. default true"},
                                &m_sceneConfig.autoLoadCache);
  m_info.parameterRegistry->add({"mappedcache", "work from memory mapped cache file, otherwise load to sysmem. default false"},
                                &m_sceneConfig.memoryMappedCache);
  m_info.parameterRegistry->add({"processingonly", "directly terminate app once cache file was saved. default false"},
                                &m_sceneConfig.processingOnly);
  m_info.parameterRegistry->add({"processingthreadpct", "float percentage of threads during initial file load and processing into lod clusters, default 0.5 == 50 %"},
                                &m_sceneConfig.processingThreadsPct);

  m_frameConfig.frameConstants                         = {};
  m_frameConfig.externalMemoryManager                  = m_info.externalMemoryManager;
  m_frameConfig.frameConstants.wireThickness           = 2.f;
  m_frameConfig.frameConstants.wireSmoothing           = 1.f;
  m_frameConfig.frameConstants.wireColor               = {118.f / 255.f, 185.f / 255.f, 0.f};
  m_frameConfig.frameConstants.wireStipple             = 0;
  m_frameConfig.frameConstants.wireBackfaceColor       = {0.5f, 0.5f, 0.5f};
  m_frameConfig.frameConstants.wireStippleRepeats      = 5;
  m_frameConfig.frameConstants.wireStippleLength       = 0.5f;
  m_frameConfig.frameConstants.doShadow                = 1;
  m_frameConfig.frameConstants.doWireframe             = 0;
  m_frameConfig.frameConstants.ambientOcclusionRadius  = 0.1f;
  m_frameConfig.frameConstants.ambientOcclusionSamples = 2;
  m_frameConfig.frameConstants.visualize               = VISUALIZE_LOD;
  m_frameConfig.frameConstants.facetShading            = 1;

  m_frameConfig.frameConstants.lightMixer = 0.5f;
  m_frameConfig.frameConstants.skyParams  = {};

  m_rendererConfig.twoSided = true;
  // 只保留一份场景副本
  m_sceneGridConfig.numCopies = 1;
  // 下面这行可加可不加，反正 numCopies=1 时不起作用
  m_sceneGridConfig.uniqueGeometriesForCopies = false;


}
bool LodClusters::initScene(const std::filesystem::path& filePath, bool configChange)
{
  deinitScene();

  std::string fileName = nvutils::utf8FromPath(filePath);

  if(!fileName.empty())
  {
    LOGI("Loading scene %s\n", fileName.c_str());

    m_scene = std::make_unique<Scene>();
    if(!m_scene->init(filePath, m_sceneConfig, configChange))
    {
      m_scene = nullptr;
      LOGW("Loading scene failed\n");
    }
    else
    {
      findSceneClusterConfig();

      m_scene->updateSceneGrid(m_sceneGridConfig);
      m_sceneGridConfigLast = m_sceneGridConfig;
      updatedSceneGrid();


    }

    m_sceneFilePath = filePath;

    if(m_scene)
    {
      initRenderScene();
    }

    return m_scene != nullptr && m_renderScene != nullptr;
  }

  return true;
}

void LodClusters::initRenderScene()
{
  assert(m_scene);

  m_renderScene = std::make_unique<RenderScene>();

  bool success = m_renderScene->init(&m_resources, m_scene.get(), m_streamingConfig, m_tweak.useStreaming);

  // if preload fails, try streaming
  if(!m_tweak.useStreaming && !success)
  {
    // override to use streaming
    m_tweak.useStreaming     = true;
    m_tweakLast.useStreaming = true;

    if(!m_renderScene->init(&m_resources, m_scene.get(), m_streamingConfig, true))
    {
      LOGW("Init renderscene failed\n");
      deinitRenderScene();
    }
  }
  else if(!success && m_tweak.useStreaming)
  {
    LOGW("Init renderscene failed\n");
    deinitRenderScene();
  }

  m_streamingConfigLast = m_streamingConfig;
}

void LodClusters::deinitRenderScene()
{
  NVVK_CHECK(vkDeviceWaitIdle(m_app->getDevice()));
  if(m_renderScene)
  {
    m_renderScene->deinit();
    m_renderScene = nullptr;
  }
}

void LodClusters::deinitScene()
{
  deinitRenderScene();

  if(m_scene)
  {
    m_scene->deinit();
    m_scene = nullptr;
  }
}

void LodClusters::onResize(VkCommandBuffer cmd, const VkExtent2D& size)
{
  m_windowSize = size;
  m_resources.initFramebuffer(m_windowSize, m_tweak.supersample, m_tweak.hbaoFullRes);
  updateImguiImage();
  if(m_renderer)
  {
    m_renderer->updatedFrameBuffer(m_resources, *m_renderScene);
    m_rendererFboChangeID = m_resources.m_fboChangeID;
  }
}

void LodClusters::updateImguiImage()
{
  if(m_imguiTexture)
  {
    ImGui_ImplVulkan_RemoveTexture(m_imguiTexture);
    m_imguiTexture = nullptr;
  }

  VkImageView imageView = m_resources.m_frameBuffer.useResolved ? m_resources.m_frameBuffer.imgColorResolved.descriptor.imageView :
                                                                  m_resources.m_frameBuffer.imgColor.descriptor.imageView;

  assert(imageView);

  m_imguiTexture = ImGui_ImplVulkan_AddTexture(m_imguiSampler, imageView, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
}

void LodClusters::onPreRender()
{
  m_profilerTimeline->frameAdvance();
}


void LodClusters::deinitRenderer()
{
  NVVK_CHECK(vkDeviceWaitIdle(m_app->getDevice()));

  if(m_renderer)
  {
    m_renderer->deinit(m_resources);
    m_renderer = nullptr;
  }
}

void LodClusters::initRenderer(RendererType rtype)
{
  // handskaing here

  LOGI("Initializing renderer and compiling shaders\n");
  deinitRenderer();
  if(!m_renderScene)
    return;

  printf("init renderer %d\n", rtype);

  if(m_renderScene->useStreaming)
  {
    if(!m_renderScene->sceneStreaming.reloadShaders())
    {
      LOGE("RenderScene shaders failed\n");
      return;
    }
  }

  switch(rtype)
  {
    case RENDERER_RASTER_CLUSTERS_LOD:
      m_renderer = makeRendererRasterClustersLod();
      break;
    case RENDERER_RAYTRACE_CLUSTERS_LOD:
      m_renderer = makeRendererRayTraceClustersLod();
      break;
  }

  if(m_renderer && !m_renderer->init(m_resources, *m_renderScene, m_rendererConfig))
  {
    m_renderer = nullptr;
    LOGE("Renderer init failed\n");
  }

  m_rendererFboChangeID = m_resources.m_fboChangeID;
}

void LodClusters::postInitNewScene()
{
  assert(m_scene);

  glm::vec3 extent         = m_scene->m_bbox.hi - m_scene->m_bbox.lo;
  glm::vec3 center         = (m_scene->m_bbox.hi + m_scene->m_bbox.lo) * 0.5f;
  float     sceneDimension = glm::length(extent);

  m_frameConfig.frameConstants.wLightPos = center + sceneDimension;
  m_frameConfig.frameConstants.sceneSize = glm::length(m_scene->m_bbox.hi - m_scene->m_bbox.lo);

  m_tweak.hbaoRadius = m_scene->m_isBig ? 0.001f : 0.05f;

  float mirrorBoxSize = sceneDimension * 0.25f;

  m_frameConfig.frameConstants.wMirrorBox =
      glm::vec4(m_scene->m_bbox.lo.x - sceneDimension, center.y, m_scene->m_bbox.lo.z - sceneDimension, sceneDimension);

  setSceneCamera(m_sceneFilePath);

  m_frames = 0;

  m_streamingConfig.maxGroups = std::max(m_streamingConfig.maxGroups, uint32_t(m_scene->getActiveGeometryCount()));
}


void LodClusters::onAttach(nvapp::Application* app)
{
  m_app = app;

  m_tweak.supersample = 1;std::max(1, m_tweak.supersample);

  m_info.cameraManipulator->setMode(nvutils::CameraManipulator::Fly);

  m_renderer = nullptr;

  {
    VkPhysicalDeviceProperties2 physicalProperties = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    VkPhysicalDeviceShaderSMBuiltinsPropertiesNV smProperties = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_SM_BUILTINS_PROPERTIES_NV};
    physicalProperties.pNext = &smProperties;
    vkGetPhysicalDeviceProperties2(app->getPhysicalDevice(), &physicalProperties);
    // pseudo heuristic
    // larger GPUs seem better off with lower values

    if(smProperties.shaderSMCount * smProperties.shaderWarpsPerSM > 4096)
      m_frameConfig.traversalPersistentThreads = smProperties.shaderSMCount * smProperties.shaderWarpsPerSM * 2;
    else if(smProperties.shaderSMCount * smProperties.shaderWarpsPerSM > 2048 + 1024)
      m_frameConfig.traversalPersistentThreads = smProperties.shaderSMCount * smProperties.shaderWarpsPerSM * 4;
    else
      m_frameConfig.traversalPersistentThreads = smProperties.shaderSMCount * smProperties.shaderWarpsPerSM * 8;
  }

  {
    m_ui.enumAdd(GUI_RENDERER, RENDERER_RASTER_CLUSTERS_LOD, "Rasterization");

    m_ui.enumAdd(GUI_BUILDMODE, 0, "default");
    m_ui.enumAdd(GUI_BUILDMODE, VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_BUILD_BIT_KHR, "fast build");
    m_ui.enumAdd(GUI_BUILDMODE, VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR, "fast trace");

    if(!m_resources.m_supportsClusters)
    {
      LOGW("WARNING: Cluster raytracing extension not supported\n");
      if(m_tweak.renderer == RENDERER_RAYTRACE_CLUSTERS_LOD)
      {
        m_tweak.renderer = RENDERER_RASTER_CLUSTERS_LOD;
      }
    }
    else
    {
      m_ui.enumAdd(GUI_RENDERER, RENDERER_RAYTRACE_CLUSTERS_LOD, "Ray tracing");
    }

    {
      for(uint32_t i = 0; i < NUM_CLUSTER_CONFIGS; i++)
      {
        std::string enumStr = fmt::format("{}T_{}V", s_clusterInfos[i].tris, s_clusterInfos[i].verts);
        m_ui.enumAdd(GUI_MESHLET, s_clusterInfos[i].cfg, enumStr.c_str());
      }
    }

    m_ui.enumAdd(GUI_SUPERSAMPLE, 1, "none");
    m_ui.enumAdd(GUI_SUPERSAMPLE, 2, "4x");

    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_MATERIAL, "material");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_GREY, "grey");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_CLUSTER, "clusters");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_GROUP, "cluster groups");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_LOD, "lods");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_TRIANGLE, "triangles");
    m_ui.enumAdd(GUI_VISUALIZE, VISUALIZE_BLAS, "blas");
  }

  // Initialize core components

  m_profilerGpuTimer.init(m_profilerTimeline, app->getDevice(), app->getPhysicalDevice(), app->getQueue(0).familyIndex, true);
  m_resources.init(app->getDevice(), app->getPhysicalDevice(), app->getInstance(), app->getQueue(0), app->getQueue(1));

  {
    NVVK_CHECK(m_resources.m_samplerPool.acquireSampler(m_imguiSampler));
    NVVK_DBG_NAME(m_imguiSampler);
  }

  m_resources.initFramebuffer({128, 128}, m_tweak.supersample, m_tweak.hbaoFullRes);
  updateImguiImage();

  updatedClusterConfig();

  // Search for default scene if none was provided on the command line
  if(m_sceneFilePath.empty())
  {
    const std::filesystem::path              exeDirectoryPath   = nvutils::getExecutablePath().parent_path();
    const std::vector<std::filesystem::path> defaultSearchPaths = {
        // regular build
        std::filesystem::absolute(exeDirectoryPath / TARGET_EXE_TO_DOWNLOAD_DIRECTORY),
        // install build
        std::filesystem::absolute(exeDirectoryPath / "resources"),
    };

    // m_sceneFilePath = nvutils::findFile("bunny_v2/bunny.gltf", defaultSearchPaths);
    m_sceneFilePath = nvutils::findFile("house_new.glb", defaultSearchPaths);
    // enforce unique geometries in the sample scene
    m_sceneGridConfig.uniqueGeometriesForCopies = true;

    // Comment out the automatic grid setup to respect user's --gridcopies parameter
    /*
    if(m_sceneGridConfig.numCopies == 1)
    {
      if(m_resources.getDeviceLocalHeapSize() >= 8ull * 1024 * 1024 * 1024)
      {
        m_sceneGridConfig.numCopies = 1024;  // 32x32 grid
      }
      else
      {
        m_sceneGridConfig.numCopies = 64;
      }
    }
    */
  }

  if(m_resources.getDeviceLocalHeapSize() >= 8ull * 1024 * 1024 * 1024)
  {
    m_streamingConfig.maxClasMegaBytes     = 2 * 1024;
    m_streamingConfig.maxGeometryMegaBytes = 2 * 1024;
  }
  else
  {
    m_streamingConfig.maxClasMegaBytes     = 1 * 1024;
    m_streamingConfig.maxGeometryMegaBytes = 1 * 1024;
  }

  if(initScene(m_sceneFilePath, false))
  {
    postInitNewScene();
    initRenderer(m_tweak.renderer);
    m_sceneInitialized = true;  // Mark scene as initialized
    LOGI("Scene initialization complete - ready for rendering\n");
  }

  m_tweakLast          = m_tweak;
  m_sceneConfigLast    = m_sceneConfig;
  m_rendererConfigLast = m_rendererConfig;
}

void LodClusters::onDetach()
{
  NVVK_CHECK(vkDeviceWaitIdle(m_app->getDevice()));

  deinitRenderer();
  deinitScene();

  m_resources.m_samplerPool.releaseSampler(m_imguiSampler);
  ImGui_ImplVulkan_RemoveTexture(m_imguiTexture);

  m_resources.deinit();

  m_profilerGpuTimer.deinit();
}

void LodClusters::saveCacheFile()
{
  if(m_scene)
  {
    m_scene->saveCache();
  }
}

void LodClusters::onFileDrop(const std::filesystem::path& filePath)
{
  // reset grid parameter (in case scene is too large to be replicated)
  m_sceneGridConfig.numCopies = 1;

  if(filePath.empty())
    return;
  LOGI("Loading model: %s\n", nvutils::utf8FromPath(filePath).c_str());
  deinitRenderer();

  if(initScene(filePath, false))
  {
    postInitNewScene();
    initRenderer(m_tweak.renderer);
    m_tweakLast       = m_tweak;
    m_sceneConfigLast = m_sceneConfig;
  }
}


const LodClusters::ClusterInfo LodClusters::s_clusterInfos[NUM_CLUSTER_CONFIGS] = {
    {64, 64, CLUSTER_64T_64V},     {64, 128, CLUSTER_64T_128V},   {64, 192, CLUSTER_64T_192V},
    {96, 96, CLUSTER_96T_96V},     {128, 128, CLUSTER_128T_128V}, {128, 256, CLUSTER_128T_256V},
    {256, 256, CLUSTER_256T_256V},
};

void LodClusters::findSceneClusterConfig()
{
  for(uint32_t i = 0; i < NUM_CLUSTER_CONFIGS; i++)
  {
    const ClusterInfo& entry = s_clusterInfos[i];
    if(m_scene->m_config.clusterTriangles <= entry.tris && m_scene->m_config.clusterVertices <= entry.verts)
    {
      m_tweak.clusterConfig = entry.cfg;
      return;
    }
  }
}

void LodClusters::updatedClusterConfig()
{
  for(uint32_t i = 0; i < NUM_CLUSTER_CONFIGS; i++)
  {
    if(s_clusterInfos[i].cfg == m_tweak.clusterConfig)
    {
      m_sceneConfig.clusterTriangles = s_clusterInfos[i].tris;
      m_sceneConfig.clusterVertices  = s_clusterInfos[i].verts;
      return;
    }
  }
}

void LodClusters::updatedSceneGrid()
{
  {
    glm::vec3 gridExtent = m_scene->m_gridBbox.hi - m_scene->m_gridBbox.lo;
    float     gridRadius = glm::length(gridExtent) * 0.5f;

    glm::vec3 modelExtent = m_scene->m_bbox.hi - m_scene->m_bbox.lo;
    float     modelRadius = glm::length(modelExtent) * 0.5f;

    bool bigScene = m_scene->m_isBig;

    m_info.cameraManipulator->setSpeed(modelRadius * (bigScene ? 0.0025f : 0.25f));
    m_info.cameraManipulator->setClipPlanes(
        glm::vec2((bigScene ? 0.0001f : 0.01F) * modelRadius,
                  bigScene ? gridRadius * 1.2f : std::max(50.0f * modelRadius, gridRadius * 1.2f)));
  }

  if(m_tweak.autoSharing)
  {
    m_rendererConfig.useBlasSharing = (m_scene->m_instances.size() > m_scene->getActiveGeometryCount() * 3);
  }
}

void LodClusters::handleChanges()
{
  
  if(m_tweak.clusterConfig != m_tweakLast.clusterConfig)
  {
    updatedClusterConfig();
  }

  if(m_rendererConfig.useBlasSharing && m_scene && m_scene->m_instances.size() > (1 << 27))
  {
    m_rendererConfig.useBlasSharing = false;
  }

  bool sceneChanged = false;
  if(memcmp(&m_sceneConfig, &m_sceneConfigLast, sizeof(m_sceneConfig)))
  {
    sceneChanged = true;

    deinitRenderer();
    initScene(m_sceneFilePath, true);
  }

  bool sceneGridChanged = false;
  if(!sceneChanged && memcmp(&m_sceneGridConfig, &m_sceneGridConfigLast, sizeof(m_sceneGridConfig)) && m_scene)
  {
    sceneGridChanged = true;

    deinitRenderer();

    // m_scene->updateSceneGrid(m_sceneGridConfig);
    // updatedSceneGrid();
    if (m_sceneGridConfig.numCopies > 1) {
      m_scene->updateSceneGrid(m_sceneGridConfig);
      updatedSceneGrid();
    } else {
      // 单份时，保持原场景包围盒做后续相机/裁剪面的参考
      // 如果 Scene 暴露了 m_gridBbox，可同步一下（否则略过这步也没关系）
      // m_scene->m_gridBbox = m_scene->m_bbox;
      updatedSceneGrid(); // 需要的话保留，里面主要是相机速度/裁剪面设置
    }


  }

  bool shaderChanged = false;
  if(m_reloadShaders)
  {
    shaderChanged   = true;
    m_reloadShaders = false;
  }

  bool frameBufferChanged = false;
  if(tweakChanged(m_tweak.supersample) || tweakChanged(m_tweak.hbaoFullRes))
  {
    m_resources.initFramebuffer(m_windowSize, m_tweak.supersample, m_tweak.hbaoFullRes);
    updateImguiImage();

    frameBufferChanged = true;
  }

  bool renderSceneChanged = false;
  if(sceneGridChanged || tweakChanged(m_tweak.useStreaming)
     || (memcmp(&m_streamingConfig, &m_streamingConfigLast, sizeof(m_streamingConfig))))
  {
    if(!sceneChanged || !sceneGridChanged)
    {
      deinitRenderer();
    }

    renderSceneChanged = true;
    deinitRenderScene();
    initRenderScene();
  }

  bool rendererChanged = false;
  if(sceneChanged || shaderChanged || renderSceneChanged || tweakChanged(m_tweak.renderer)
     || rendererCfgChanged(m_rendererConfig.flipWinding) || rendererCfgChanged(m_rendererConfig.useDebugVisualization)
     || rendererCfgChanged(m_rendererConfig.useCulling) || rendererCfgChanged(m_rendererConfig.twoSided)
     || rendererCfgChanged(m_rendererConfig.useSorting) || rendererCfgChanged(m_rendererConfig.numRenderClusterBits)
     || rendererCfgChanged(m_rendererConfig.numTraversalTaskBits) || rendererCfgChanged(m_rendererConfig.useBlasSharing)
     || rendererCfgChanged(m_rendererConfig.useRenderStats) || rendererCfgChanged(m_rendererConfig.useSeparateGroups)
  #if USE_DLSS
      || rendererCfgChanged(m_rendererConfig.useDlss) || rendererCfgChanged(m_rendererConfig.dlssQuality)
  #endif
  )
  {
    rendererChanged = true;

    initRenderer(m_tweak.renderer);
  }
  else if(m_renderer && frameBufferChanged)
  {
    m_renderer->updatedFrameBuffer(m_resources, *m_renderScene);
    m_rendererFboChangeID = m_resources.m_fboChangeID;
  }

  bool hadChange = shaderChanged || memcmp(&m_tweakLast, &m_tweak, sizeof(m_tweak))
                   || memcmp(&m_rendererConfigLast, &m_rendererConfig, sizeof(m_rendererConfig))
                   || memcmp(&m_sceneConfigLast, &m_sceneConfig, sizeof(m_sceneConfig))
                   || memcmp(&m_streamingConfigLast, &m_streamingConfig, sizeof(m_streamingConfig))
                   || memcmp(&m_sceneGridConfigLast, &m_sceneGridConfig, sizeof(m_sceneGridConfig));
  m_tweakLast           = m_tweak;
  m_rendererConfigLast  = m_rendererConfig;
  m_streamingConfigLast = m_streamingConfig;
  m_sceneConfigLast     = m_sceneConfig;
  m_sceneGridConfigLast = m_sceneGridConfig;

  if(hadChange)
  {
    m_equalFrames = 0;
    if(m_tweak.autoResetTimers)
    {
      m_info.profilerManager->resetFrameSections(8);
    }
  }
}

void LodClusters::onRender(VkCommandBuffer cmd)
{

  bool verbose = false;
  if(m_app->isHeadless())
  {
    // If we have external memory manager and scene is initialized, wait for connection
    if (m_frameConfig.externalMemoryManager && m_sceneInitialized && 
        !m_frameConfig.externalMemoryManager->isConnected()) 
    {
      if (!m_waitingForConnection) {
        if (verbose)
        {
          LOGI("Scene initialized - waiting for Python client connection...\n");
          LOGI("Blocking until Python connects to start rendering...\n");
        }

        
        // In headless mode, block synchronously
        if (m_app->isHeadless()) {
          if (m_frameConfig.externalMemoryManager->acceptClient()) {
            LOGI("Python client connected! Starting rendering...\n");
          } else {
            LOGE("Failed to accept Python client\n");
            return;
          }
        } else {
          // In GUI mode, just return and wait
          m_waitingForConnection = true;
          return;
        }
      } else {
        // Still waiting in GUI mode
        return;
      }
    }
   }
  // Reset waiting flag once connected
  if (m_waitingForConnection && m_frameConfig.externalMemoryManager && 
      m_frameConfig.externalMemoryManager->isConnected()) {
    m_waitingForConnection = false;
    if (verbose)
    LOGI("Python client connected! Starting rendering...\n");
  }

  static int renderCount = 0;
  static int externalFrameCount = 0;
  if (renderCount < 10 || renderCount % 100 == 0) {
    if (verbose)
    LOGI("onRender called (count: %d)\n", renderCount);
  }
  renderCount++;
  
  double time = m_clock.getSeconds();

  m_resources.beginFrame(m_app->getFrameCycleIndex());


  // 如果当前“已知布局”是 SRV，则把 depth 和 stencil 一次性拉回 DS_ATTACHMENT
  if (m_resources.m_frameBuffer.imgDepthStencil.descriptor.imageLayout ==
      VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL)
  {
    // printf("this is hit");
    VkImage img = m_resources.m_frameBuffer.imgDepthStencil.image;

    VkImageMemoryBarrier2 bs[2] = {};
    // DEPTH: SRV -> DS_ATTACHMENT
    bs[0].sType         = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2;
    bs[0].srcStageMask  = VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT;
    bs[0].srcAccessMask = VK_ACCESS_2_SHADER_SAMPLED_READ_BIT;
    bs[0].dstStageMask  = VK_PIPELINE_STAGE_2_EARLY_FRAGMENT_TESTS_BIT;
    bs[0].dstAccessMask = VK_ACCESS_2_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    bs[0].oldLayout     = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    bs[0].newLayout     = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
    bs[0].image         = img;
    bs[0].subresourceRange = {VK_IMAGE_ASPECT_DEPTH_BIT, 0,1,0,1};

    // STENCIL: SRV -> DS_ATTACHMENT
    bs[1]              = bs[0];
    bs[1].subresourceRange.aspectMask = VK_IMAGE_ASPECT_STENCIL_BIT;

    VkDependencyInfo dep{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    dep.imageMemoryBarrierCount = 2;
    dep.pImageMemoryBarriers    = bs;
    vkCmdPipelineBarrier2(cmd, &dep);

    // 更新追踪器
    m_resources.m_frameBuffer.imgDepthStencil.descriptor.imageLayout =
        VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
  }


  m_frameConfig.windowSize = m_windowSize;
  m_frameConfig.hbaoActive = false;
  
  // Track if we should process external memory this frame
  bool shouldProcessExternalFrame = false;

  if(m_renderer)
  {
    if(m_rendererFboChangeID != m_resources.m_fboChangeID)
    {
      m_renderer->updatedFrameBuffer(m_resources, *m_renderScene);
      m_rendererFboChangeID = m_resources.m_fboChangeID;
    }

    m_frameConfig.hbaoActive = m_tweak.hbaoActive && m_tweak.renderer == RENDERER_RASTER_CLUSTERS_LOD;

    shaderio::FrameConstants& frameConstants = m_frameConfig.frameConstants;

    // for motion always use last
    frameConstants.viewProjMatrixPrev = frameConstants.viewProjMatrix;

    if(m_frames && !m_frameConfig.freezeCulling)
    {
      m_frameConfig.frameConstantsLast = m_frameConfig.frameConstants;
    }

    int supersample = m_tweak.supersample;

    uint32_t renderWidth  = m_resources.m_frameBuffer.renderSize.width;
    uint32_t renderHeight = m_resources.m_frameBuffer.renderSize.height;

    frameConstants.facetShading = m_tweak.facetShading ? 1 : 0;
    frameConstants.visualize    = m_frameConfig.visualize;
    frameConstants.frame        = m_frames;

    {
      frameConstants.visFilterClusterID  = ~0;
      frameConstants.visFilterInstanceID = ~0;
    }

    frameConstants.bgColor     = m_resources.m_bgColor;
    frameConstants.flipWinding = m_rendererConfig.flipWinding ? 1 : 0;
    if(m_rendererConfig.twoSided)
    {
      frameConstants.flipWinding = 2;
    }

    frameConstants.viewport    = glm::ivec2(renderWidth, renderHeight);
    frameConstants.viewportf   = glm::vec2(renderWidth, renderHeight);
    frameConstants.supersample = m_tweak.supersample;
    frameConstants.nearPlane   = m_info.cameraManipulator->getClipPlanes().x;
    frameConstants.farPlane    = m_info.cameraManipulator->getClipPlanes().y;
    frameConstants.wUpDir      = m_info.cameraManipulator->getUp();
  #if USE_DLSS
    frameConstants.jitter = shaderio::dlssJitter(m_frames);
  #endif
    frameConstants.fov = glm::radians(m_info.cameraManipulator->getFov());

    glm::mat4 projection =
        glm::perspectiveRH_ZO(glm::radians(m_info.cameraManipulator->getFov()), float(renderWidth) / float(renderHeight),
                              frameConstants.nearPlane, frameConstants.farPlane);
    projection[1][1] *= -1;

    glm::mat4 view  = m_info.cameraManipulator->getViewMatrix();
    glm::mat4 viewI = glm::inverse(view);

    frameConstants.viewProjMatrix  = projection * view;
    frameConstants.viewProjMatrixI = glm::inverse(frameConstants.viewProjMatrix);
    frameConstants.viewMatrix      = view;
    frameConstants.viewMatrixI     = viewI;
    frameConstants.projMatrix      = projection;
    frameConstants.projMatrixI     = glm::inverse(projection);

    glm::mat4 viewNoTrans         = view;
    viewNoTrans[3]                = {0.0f, 0.0f, 0.0f, 1.0f};
    frameConstants.skyProjMatrixI = glm::inverse(projection * viewNoTrans);

    glm::vec4 hPos   = projection * glm::vec4(1.0f, 1.0f, -frameConstants.farPlane, 1.0f);
    glm::vec2 hCoord = glm::vec2(hPos.x / hPos.w, hPos.y / hPos.w);
    glm::vec2 dim    = glm::abs(hCoord);

    // helper to quickly get footprint of a point at a given distance
    //
    // __.__hPos (far plane is width x height)
    // \ | /
    //  \|/
    //   x camera
    //
    // here: viewPixelSize / point.w = size of point in pixels
    // * 0.5f because renderWidth/renderHeight represents [-1,1] but we need half of frustum
    frameConstants.viewPixelSize = dim * (glm::vec2(float(renderWidth), float(renderHeight)) * 0.5f) * frameConstants.farPlane;
    // here: viewClipSize / point.w = size of point in clip-space units
    // no extra scale as half clip space is 1.0 in extent
    frameConstants.viewClipSize = dim * frameConstants.farPlane;

    frameConstants.viewPos = frameConstants.viewMatrixI[3];  // position of eye in the world
    frameConstants.viewDir = -viewI[2];

    frameConstants.viewPlane   = frameConstants.viewDir;
    frameConstants.viewPlane.w = -glm::dot(glm::vec3(frameConstants.viewPos), glm::vec3(frameConstants.viewDir));

    frameConstants.wLightPos = frameConstants.viewMatrixI[3];  // place light at position of eye in the world

    {
      // hiz
      m_resources.m_hizUpdate.farInfo.getShaderFactors((float*)&frameConstants.hizSizeFactors);
      frameConstants.hizSizeMax = m_resources.m_hizUpdate.farInfo.getSizeMax();
    }

    {
      // hbao setup
      auto& hbaoView                    = m_frameConfig.hbaoSettings.view;
      hbaoView.farPlane                 = frameConstants.farPlane;
      hbaoView.nearPlane                = frameConstants.nearPlane;
      hbaoView.isOrtho                  = false;
      hbaoView.projectionMatrix         = projection;
      m_frameConfig.hbaoSettings.radius = glm::length(m_scene->m_bbox.hi - m_scene->m_bbox.lo) * m_tweak.hbaoRadius;

      glm::vec4 hi = frameConstants.projMatrixI * glm::vec4(1, 1, -0.9, 1);
      hi /= hi.w;
      float tanx           = hi.x / fabsf(hi.z);
      float tany           = hi.y / fabsf(hi.z);
      hbaoView.halfFovyTan = tany;
    }

    if(!m_frames)
    {
      m_frameConfig.frameConstantsLast = m_frameConfig.frameConstants;
    }

    if(m_frames)
    {
      shaderio::FrameConstants frameCurrent = m_frameConfig.frameConstants;

      if(memcmp(&frameCurrent, &m_frameConfig.frameConstantsLast, sizeof(shaderio::FrameConstants)))
        m_equalFrames = 0;
      else
        m_equalFrames++;
    }

    // External memory frame protocol: Wait for camera ready before rendering
    bool shouldProcessExternalFrame = false;




    if(m_frameConfig.externalMemoryManager && m_frameConfig.externalMemoryManager->isConnected())
    {
      //printf("this is hit");
      // Only process external memory protocol once per actual frame
      // Check if we haven't processed this frame yet
      static uint64_t lastProcessedExternalFrame = 0;
      uint64_t currentFrame = m_frames;  // Use the actual frame counter
      
      if (currentFrame > lastProcessedExternalFrame) {
        shouldProcessExternalFrame = true;
        lastProcessedExternalFrame = currentFrame;
        
        // Get the next frame number and use it consistently throughout this frame
        uint64_t frameNumber = m_frameConfig.externalMemoryManager->getNextFrameNumber();
        
        // Store it for later use when signaling frame done
        m_currentExternalFrameNumber = frameNumber;
        if (verbose)
        LOGI("====== Frame %lu: External memory protocol active (app frame: %lu, onRender: %d) ======\n", 
             frameNumber, currentFrame, renderCount - 1);
      
        // For the first few frames after connection, don't wait for camera ready
        // This allows the render loop to start and Python to synchronize
        static int framesAfterConnection = 0;
        if (framesAfterConnection < -1) {
          framesAfterConnection++;
          if (verbose)
          LOGI("Frame %lu: Skipping camera wait (frame %d after connection)\n", frameNumber, framesAfterConnection);
        } else {
          // Wait for Python to signal camera ready
          // This is a synchronous wait - the frame will not proceed until Python provides camera data
          if (verbose)
          LOGI("Frame %lu: Waiting for camera ready signal...\n", frameNumber);

          if(!m_frameConfig.externalMemoryManager->waitForCameraReady(frameNumber))
          {
            LOGW("Frame %lu: Camera ready timeout, proceeding with existing camera data\n", frameNumber);
          }
          else
          {
            if (verbose)
            LOGI("Frame %lu: Camera ready signal received, now receiving camera matrices...\n", frameNumber);
            
            // Receive camera matrices from Python via socket
            float viewMatrix[16], projMatrix[16];
            if (m_frameConfig.externalMemoryManager->receiveCameraMatrices(viewMatrix, projMatrix)) {
              // Print received matrices in detail
              if (verbose)
              {
                LOGI("Frame %lu: Received camera matrices from Python:\n", frameNumber);
                LOGI("  View Matrix:\n");
                for (int row = 0; row < 4; row++) {
                  LOGI("    [%8.4f %8.4f %8.4f %8.4f]\n", 
                      viewMatrix[row*4], viewMatrix[row*4+1], 
                      viewMatrix[row*4+2], viewMatrix[row*4+3]);
                }
                LOGI("  Projection Matrix:\n");
                for (int row = 0; row < 4; row++) {
                  LOGI("    [%8.4f %8.4f %8.4f %8.4f]\n",
                      projMatrix[row*4], projMatrix[row*4+1],
                      projMatrix[row*4+2], projMatrix[row*4+3]);
                }
              }

              
              // Convert from float arrays to glm::mat4 (column-major)
              glm::mat4 pythonView = glm::mat4(
                viewMatrix[0], viewMatrix[1], viewMatrix[2], viewMatrix[3],
                viewMatrix[4], viewMatrix[5], viewMatrix[6], viewMatrix[7],
                viewMatrix[8], viewMatrix[9], viewMatrix[10], viewMatrix[11],
                viewMatrix[12], viewMatrix[13], viewMatrix[14], viewMatrix[15]
              );
              
              glm::mat4 pythonProj = glm::mat4(
                projMatrix[0], projMatrix[1], projMatrix[2], projMatrix[3],
                projMatrix[4], projMatrix[5], projMatrix[6], projMatrix[7],
                projMatrix[8], projMatrix[9], projMatrix[10], projMatrix[11],
                projMatrix[12], projMatrix[13], projMatrix[14], projMatrix[15]
              );
              
              // Override the frame constants with Python's camera matrices
              frameConstants.viewMatrix = pythonView;
              frameConstants.projMatrix = pythonProj;
              frameConstants.viewMatrixI = glm::inverse(pythonView);
              frameConstants.projMatrixI = glm::inverse(pythonProj);
              frameConstants.viewProjMatrix = pythonProj * pythonView;
              frameConstants.viewProjMatrixI = glm::inverse(frameConstants.viewProjMatrix);
              
              // Update derived camera properties
              frameConstants.viewPos = frameConstants.viewMatrixI[3];  // Camera position
              frameConstants.viewDir = -frameConstants.viewMatrixI[2]; // Camera direction
              frameConstants.viewPlane = frameConstants.viewDir;
              frameConstants.viewPlane.w = -glm::dot(glm::vec3(frameConstants.viewPos), glm::vec3(frameConstants.viewDir));
              
              // Update sky matrix
              glm::mat4 viewNoTrans = pythonView;
              viewNoTrans[3] = {0.0f, 0.0f, 0.0f, 1.0f};
              frameConstants.skyProjMatrixI = glm::inverse(pythonProj * viewNoTrans);
              if (verbose)
              {
                // Print extracted camera information
                LOGI("  Extracted Camera Position: [%.4f, %.4f, %.4f]\n",
                    frameConstants.viewPos.x, frameConstants.viewPos.y, frameConstants.viewPos.z);
                LOGI("  Extracted Camera Direction: [%.4f, %.4f, %.4f]\n",
                    frameConstants.viewDir.x, frameConstants.viewDir.y, frameConstants.viewDir.z);
                
                LOGI("Frame %lu: Successfully updated frame constants with Python camera matrices\n", frameNumber);
              }

            } else {
              LOGW("Frame %lu: Failed to receive camera matrices, using default camera\n", frameNumber);
            }
          }

          
        }
      }  // end if (currentFrame > lastProcessedExternalFrame)
    }  // end if (externalMemoryManager && isConnected)

    m_renderer->render(cmd, m_resources, *m_renderScene, m_frameConfig, m_profilerGpuTimer);
  }
  else
  {
    m_resources.emptyFrame(cmd, m_frameConfig, m_profilerGpuTimer);
  }

  {
    m_resources.postProcessFrame(cmd, m_frameConfig, m_profilerGpuTimer);
  }

 

  // External memory frame protocol integration (window mode)
  // Check if we have an active external frame number to process
  if(m_frameConfig.externalMemoryManager && m_frameConfig.externalMemoryManager->isConnected() && m_currentExternalFrameNumber > 0)
  {
    // Choose the appropriate final color image (resolved if MSAA is used)
    VkImage finalImage = m_resources.m_frameBuffer.useResolved ? 
                          m_resources.m_frameBuffer.imgColorResolved.image :
                          m_resources.m_frameBuffer.imgColor.image;
    VkImageLayout finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;  // Typical layout after rendering
    
    const VkImageLayout currentLayout =
        m_resources.m_frameBuffer.useResolved ?
          m_resources.m_frameBuffer.imgColorResolved.descriptor.imageLayout : // 若你没有，至少传 COLOR_ATTACHMENT_OPTIMAL
          m_resources.m_frameBuffer.imgColor.descriptor.imageLayout;


    const auto& tex = m_resources.m_frameBuffer.useResolved ?
                        m_resources.m_frameBuffer.imgColorResolved :
                        m_resources.m_frameBuffer.imgColor;
    VkImageLayout depthKnownLayout =
        m_resources.m_frameBuffer.imgDepthStencil.descriptor.imageLayout;

    // m_frameConfig.externalMemoryManager->cmdCopyImageToColorBuffer(
    //     cmd, finalImage, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, 
    //     tex.extent.width, 
    //     tex.extent.height
    // );
    // 假设你的深度图句柄是 depthImage，当前布局是 DEPTH_STENCIL_ATTACHMENT_OPTIMAL
    m_frameConfig.externalMemoryManager->cmdCopyDepthToBuffer(
        cmd, m_resources.m_frameBuffer.imgDepthStencil.image, depthKnownLayout,
        tex.extent.width, tex.extent.height);

    m_resources.m_frameBuffer.imgDepthStencil.descriptor.imageLayout =
        VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;




    LOGI("Frame %lu: External memory copy added to command buffer\n", m_currentExternalFrameNumber);
  }

  m_resources.endFrame();
  // signal new semaphore state with this command buffer's submit
  VkSemaphoreSubmitInfo semSubmit = m_resources.m_queueStates.primary.advanceSignalSubmit(VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT);
  m_app->addSignalSemaphore(semSubmit);
  
  // Add frame done semaphore if we have an active external frame
  // CRITICAL: Only signal if we actually processed a NEW external frame this render call
  static uint64_t lastSignaledFrameNumber = 0;
  
  // Frame done signal
  if(m_frameConfig.externalMemoryManager && m_frameConfig.externalMemoryManager->isConnected() 
     && m_currentExternalFrameNumber > 0 
     && m_currentExternalFrameNumber > lastSignaledFrameNumber)
  {
    externalFrameCount++;
    
    VkSemaphoreSubmitInfo frameDoneSubmit{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
    frameDoneSubmit.semaphore = m_frameConfig.externalMemoryManager->getFrameDoneSemaphore();
    frameDoneSubmit.value = m_currentExternalFrameNumber;
    frameDoneSubmit.stageMask = VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT;
    
    LOGI("Frame %lu: Signaling frame done semaphore with value %lu (external frame count: %d, last signaled: %lu)\n", 
         m_currentExternalFrameNumber, frameDoneSubmit.value, externalFrameCount, lastSignaledFrameNumber);
    
    // Double-check we're not signaling a duplicate or out-of-order value
    if (frameDoneSubmit.value <= lastSignaledFrameNumber) {
      LOGE("CRITICAL ERROR: Attempting to signal timeline semaphore with value %lu but already signaled %lu!\n", 
           frameDoneSubmit.value, lastSignaledFrameNumber);
      LOGE("SKIPPING frame done signal to prevent GPU crash\n");
    } else {
      lastSignaledFrameNumber = frameDoneSubmit.value;
      //m_app->addSignalSemaphore(frameDoneSubmit);
       m_frameConfig.externalMemoryManager->signalFrameDone(frameDoneSubmit.value,m_app->getQueue(0).queue);
      LOGI("Frame %lu: Frame done semaphore successfully added to submit\n", m_currentExternalFrameNumber);
      
      // Don't clear here as it might be needed for image copy
    }
  } else if (m_currentExternalFrameNumber > 0 && m_currentExternalFrameNumber == lastSignaledFrameNumber) {
    LOGI("Frame %lu: Already signaled, skipping duplicate signal\n", m_currentExternalFrameNumber);
  }
  // but also enqueue waits if there are any
  while(!m_resources.m_queueStates.primary.m_pendingWaits.empty())
  {
    m_app->addWaitSemaphore(m_resources.m_queueStates.primary.m_pendingWaits.back());
    m_resources.m_queueStates.primary.m_pendingWaits.pop_back();
  }

  m_lastTime = time;
  m_frames++;
}

void LodClusters::setSceneCamera(const std::filesystem::path& filePath)
{
  nvgui::SetCameraJsonFile(filePath);

  glm::vec3 modelExtent = m_scene->m_bbox.hi - m_scene->m_bbox.lo;
  float     modelRadius = glm::length(modelExtent) * 0.5f * 0.1f;
  glm::vec3 modelCenter = (m_scene->m_bbox.hi + m_scene->m_bbox.lo) * 0.5f;

  bool bigScene = m_scene->m_isBig;

  if(!m_scene->m_cameras.empty())
  {
    auto& c = m_scene->m_cameras[0];
    m_info.cameraManipulator->setFov(c.fovy);


    c.eye              = glm::vec3(c.worldMatrix[3]);
    float     distance = glm::length(modelCenter - c.eye);
    glm::mat3 rotMat   = glm::mat3(c.worldMatrix);
    c.center           = {0, 0, -distance};
    c.center           = c.eye + (rotMat * c.center);
    c.up               = {0, 1, 0};

    m_info.cameraManipulator->setCamera({c.eye, c.center, c.up, static_cast<float>(glm::degrees(c.fovy))});

    nvgui::SetHomeCamera({c.eye, c.center, c.up, static_cast<float>(glm::degrees(c.fovy))});
    for(auto& cam : m_scene->m_cameras)
    {
      cam.eye            = glm::vec3(cam.worldMatrix[3]);
      float     distance = glm::length(modelCenter - cam.eye);
      glm::mat3 rotMat   = glm::mat3(cam.worldMatrix);
      cam.center         = {0, 0, -distance};
      cam.center         = cam.eye + (rotMat * cam.center);
      cam.up             = {0, 1, 0};


      nvgui::AddCamera({cam.eye, cam.center, cam.up, static_cast<float>(glm::degrees(cam.fovy))});
    }
  }
  else
  {
    glm::vec3 up  = {0, 1, 0};
    glm::vec3 dir = {1.0f, bigScene ? 0.33f : 0.75f, 1.0f};

    m_info.cameraManipulator->setLookat(modelCenter + dir * (modelRadius * (bigScene ? 0.5f : 1.f)), modelCenter, up);
    nvgui::SetHomeCamera(m_info.cameraManipulator->getCamera());
  }
}

float LodClusters::decodePickingDepth(const shaderio::Readback& readback)
{
  if(!isPickingValid(readback))
  {
    return 0.f;
  }
  uint32_t bits = readback._packedDepth0;
  bits ^= ~(int(bits) >> 31) | 0x80000000u;
  float res = *(float*)&bits;
  return 1.f - res;
}

bool LodClusters::isPickingValid(const shaderio::Readback& readback)
{
  return readback._packedDepth0 != 0u;
}

void LodClusters::setExternalMemoryManager(ExternalMemoryManager* manager)
{
  m_externalMemoryManager = manager;
  m_frameConfig.externalMemoryManager = manager;
  LOGI("External memory manager set for Python integration\n");
}

}  // namespace lodclusters
