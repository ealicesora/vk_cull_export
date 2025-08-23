#!/usr/bin/env bash
set -euo pipefail

echo "=== Building vk_lod_clusters with forced system libraries (Route B) ==="

# 强迫链接到系统 libstdc++，覆盖 conda 路径
export LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
export LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
unset PKG_CONFIG_PATH || true
export PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig"

# 强制系统编译器
export CC=/usr/bin/gcc-10
export CXX=/usr/bin/g++-10

# VulkanSDK 设置（保持现有）
VULKAN_SDK_BASE="${HOME}/VulkanSDK"
if [ -d "${VULKAN_SDK_BASE}" ]; then
    VULKAN_VERSION=$(find "${VULKAN_SDK_BASE}" -maxdepth 1 -name "1.*" -type d | sort -V | tail -1)
    if [ -n "${VULKAN_VERSION}" ] && [ -d "${VULKAN_VERSION}/x86_64" ]; then
        export VULKAN_SDK="${VULKAN_VERSION}/x86_64"
        export PATH="$VULKAN_SDK/bin:$PATH"
        echo "Using VulkanSDK: $VULKAN_SDK"
    fi
fi

echo "Environment (Route B):"
echo "  CC: $CC"
echo "  CXX: $CXX"
echo "  LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
echo "  LIBRARY_PATH: $LIBRARY_PATH"
echo "  PKG_CONFIG_PATH: $PKG_CONFIG_PATH"
echo "  VULKAN_SDK: ${VULKAN_SDK:-'(system)'}"
echo ""

# 清理旧构建
echo "Cleaning old build..."
rm -rf build-conda

# 配置构建 - 强制系统库路径
echo "Configuring build with forced system library paths..."
cmake -S . -B build-conda \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$CC" \
  -DCMAKE_CXX_COMPILER="$CXX" \
  ${VULKAN_SDK:+-DCMAKE_PREFIX_PATH="$VULKAN_SDK"} \
  -DCMAKE_INSTALL_RPATH="/usr/lib/x86_64-linux-gnu" \
  -DCMAKE_BUILD_RPATH="/usr/lib/x86_64-linux-gnu" \
  -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON \
  -DUSE_DLSS=OFF \
  -DCMAKE_VERBOSE_MAKEFILE=ON

echo ""
echo "Building with system library paths..."
cmake --build build-conda -j4 --config Release

echo ""
echo "Build completed! Checking result..."

# 验证可执行文件
if [ -f "build-conda/_bin/Release/vk_lod_clusters" ]; then
    echo ""
    echo "✅ Build successful!"
    echo "File info:"
    file build-conda/_bin/Release/vk_lod_clusters
    ls -la build-conda/_bin/Release/vk_lod_clusters
    
    echo ""
    echo "Library dependencies:"
    ldd build-conda/_bin/Release/vk_lod_clusters | head -10
else
    echo ""
    echo "❌ Build failed - executable not found"
    
    # 检查我们的文件是否编译成功
    echo ""
    echo "Checking if our files compiled:"
    find build-conda -name "*.o" | grep -E "(external_memory|context_bootstrap|element_pybridge|vma_impl)" | sort || echo "No object files found"
    
    exit 1
fi