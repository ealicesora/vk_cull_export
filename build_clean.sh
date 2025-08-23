#!/usr/bin/env bash
set -euo pipefail

echo "=== Building vk_lod_clusters with clean environment ==="

# 关闭 conda 影响（即使当前在 conda shell 里）
unset CONDA_PREFIX || true
unset CONDA_SHLVL || true
unset CONDA_DEFAULT_ENV || true
unset CONDA_EXE || true
unset CONDA_PYTHON_EXE || true
unset CONDA_ROOT || true
unset CONDA_PREFIX_1 || true

# 关键：彻底移除所有可能的库路径
unset LD_LIBRARY_PATH || true
unset LIBRARY_PATH || true
unset CPATH || true
unset CMAKE_PREFIX_PATH || true
unset PKG_CONFIG_PATH || true

# 清理 PATH，只保留系统路径
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# 强制清理 cmake 缓存相关环境变量
unset CMAKE_INCLUDE_PATH || true
unset CMAKE_LIBRARY_PATH || true

# 检测 VulkanSDK 版本
VULKAN_SDK_BASE="${HOME}/VulkanSDK"
if [ -d "${VULKAN_SDK_BASE}" ]; then
    # 找到最新版本的 VulkanSDK
    VULKAN_VERSION=$(find "${VULKAN_SDK_BASE}" -maxdepth 1 -name "1.*" -type d | sort -V | tail -1)
    if [ -n "${VULKAN_VERSION}" ] && [ -d "${VULKAN_VERSION}/x86_64" ]; then
        export VULKAN_SDK="${VULKAN_VERSION}/x86_64"
        export PATH="$VULKAN_SDK/bin:$PATH"
        export PKG_CONFIG_PATH="$VULKAN_SDK/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
        echo "Using VulkanSDK: $VULKAN_SDK"
    else
        echo "WARNING: VulkanSDK not found, falling back to system Vulkan packages"
        unset VULKAN_SDK || true
    fi
else
    echo "VulkanSDK not found at $VULKAN_SDK_BASE, using system Vulkan packages"
    unset VULKAN_SDK || true
fi

# 使用系统编译器
export CC=/usr/bin/gcc-10
export CXX=/usr/bin/g++-10

echo "Environment:"
echo "  CC: $CC"
echo "  CXX: $CXX"
echo "  PATH: $PATH"
echo "  VULKAN_SDK: ${VULKAN_SDK:-'(system)'}"
echo ""

# 清理旧构建
echo "Cleaning old build..."
rm -rf build-clean

# 配置构建
echo "Configuring build..."
cmake -S . -B build-clean \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$CC" \
  -DCMAKE_CXX_COMPILER="$CXX" \
  ${VULKAN_SDK:+-DCMAKE_PREFIX_PATH="$VULKAN_SDK"} \
  -DCMAKE_INSTALL_RPATH="/usr/lib/x86_64-linux-gnu" \
  -DCMAKE_BUILD_RPATH="/usr/lib/x86_64-linux-gnu" \
  -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON \
  -DUSE_DLSS=OFF \
  -DCMAKE_VERBOSE_MAKEFILE=ON

# 构建
echo ""
echo "Building..."
cmake --build build-clean -j4 --config Release

echo ""
echo "Build completed! Executable should be at:"
echo "  $(pwd)/build-clean/_bin/Release/vk_lod_clusters"

# 验证可执行文件
if [ -f "build-clean/_bin/Release/vk_lod_clusters" ]; then
    echo ""
    echo "✅ Build successful!"
    echo "File info:"
    file build-clean/_bin/Release/vk_lod_clusters
    ls -la build-clean/_bin/Release/vk_lod_clusters
else
    echo ""
    echo "❌ Build failed - executable not found"
    exit 1
fi