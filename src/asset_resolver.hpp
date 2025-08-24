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

#include <filesystem>
#include <string>
#include <cstdlib>

namespace lodclusters {

// 通用资源解析：给定相对文件，自动在若干常见子目录查找
inline std::filesystem::path resolve_asset(const std::filesystem::path& assetRoot,
                                           const std::string& rel) {
  using std::filesystem::path;
  const path base = assetRoot;
  const path relp = rel;
  const path candidates[] = {
    base / relp,
    base / "shaders" / relp,
    base / "shaders/hbao" / relp,
    base / "post" / relp,
    base / "glsl" / relp,
    // Fallback to current directory structure
    path("shaders") / relp,
    path(".") / "shaders" / relp
  };
  for (auto& c : candidates) {
    if (std::filesystem::exists(c)) return c;
  }
  return relp; // 兜底：返回原样，供旧逻辑报错时打印
}

// 获取默认资产根目录
inline std::filesystem::path get_default_asset_root() {
  // 优先环境变量
  const char* env = std::getenv("VK2TORCH_DATA_ROOT");
  if(env && *env) return std::filesystem::path(env);
  
  // 使用当前工作目录的父目录，这通常对应项目根
  auto current = std::filesystem::current_path();
  std::filesystem::path candidates[] = {
    // Check current directory first
    current,
    // Check if we're in a python extension environment
    current / "build-py" / "_bin" / "Release",
    // Standard locations
    current / "resources", 
    current / ".." / "resources",
    current / "../.." / "resources",
    // Build directory locations
    current / "shaders",
    current / ".." / "shaders", 
    current / "../.." / "shaders"
  };
  
  for (auto& c : candidates) {
    if (std::filesystem::exists(c / "shaders")) {
      return c;
    }
  }
  
  return current;
}

} // namespace lodclusters