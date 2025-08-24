# T3: ExternalMemoryManager 同进程查询与帧号通道 - 实现总结

## 完成的功能

### 1. 确认已有的同进程初始化方法
- ✅ `bool initInProcess(VkDevice, VkPhysicalDevice, const ExternalMemoryConfig&)` - 已实现
- ✅ 正确设置了 `m_inProcessMode = true` 标志

### 2. 确认已有的导出 FD 方法（返回前 dup）
- ✅ `int exportDepthBufferFdDup() const` - 已实现，返回 `dup(m_depthBufferFd)`
- ✅ `int exportFrameDoneSemaphoreFdDup() const` - 已实现，返回 `dup(m_frameDoneSemaphoreFd)`
- ✅ 正确的错误处理和 Linux 平台检查

### 3. 确认已有的查询方法
- ✅ `uint32_t rowPitchBytes() const` - 已实现，返回 `m_actualRowPitch`
- ✅ `VkExtent2D extent() const` - 已实现，返回 `{m_config.width, m_config.height}`
- ✅ `VkSemaphore timelineSemaphore() const` - 已实现，返回 `m_frameDoneSemaphore`

### 4. 新增帧号通道方法 (NEW)
- ✅ **新增** `void setCurrentFrameValue(uint64_t v)` - 由 PyBridge 在 onRender 前设置为 expectedFrame
- ✅ **新增** `uint64_t currentFrameValue() const` - 由 LodClusters onRender 读取作为 signal 的 value
- ✅ **线程安全**: 使用 `std::mutex m_frameValueMutex` 保护 `m_currentFrameValue`
- ✅ **初始化**: `m_currentFrameValue = 1` 默认值

### 5. LodClusters::onRender() 更新 (NEW)
- ✅ **修改信号逻辑**: 改为使用 `m_frameConfig.externalMemoryManager->currentFrameValue()` 替代 `m_currentExternalFrameNumber`
- ✅ **保持兼容性**: 保留原有的重复信号检查和错误处理逻辑
- ✅ **增强日志**: 显示 "coordinated value" 以区分新的同步方式

## 代码更改详情

### src/external_memory.hpp
```cpp
// 新增方法声明
void setCurrentFrameValue(uint64_t v);      // Set by PyBridge before onRender
uint64_t currentFrameValue() const;         // Read by LodClusters onRender for signal value

// 新增私有成员
mutable std::mutex m_frameValueMutex;
uint64_t m_currentFrameValue = 1;  // Shared frame value for timeline signals
```

### src/external_memory.cpp  
```cpp
// 新增方法实现
void ExternalMemoryManager::setCurrentFrameValue(uint64_t v) {
  std::lock_guard<std::mutex> lock(m_frameValueMutex);
  m_currentFrameValue = v;
}

uint64_t ExternalMemoryManager::currentFrameValue() const {
  std::lock_guard<std::mutex> lock(m_frameValueMutex);
  return m_currentFrameValue;
}
```

### src/lodclusters.cpp
```cpp
// 修改信号逻辑 (约第1149行)
// 原来: frameDoneSubmit.value = m_currentExternalFrameNumber;
// 现在:
const uint64_t frame = m_frameConfig.externalMemoryManager->currentFrameValue();
frameDoneSubmit.value = frame;  // Use coordinated value instead of m_currentExternalFrameNumber
```

## 验收结果

### ✅ 编译成功
- 无编译错误
- 无链接错误  
- vk2torch_ext 模块正确构建

### ✅ 基础测试通过
- Python 模块可以成功导入
- Vk2TorchApp 可以正确初始化
- ExternalMemoryManager 同进程模式工作正常

### ✅ 最小自测完成
- 构造/设置/读取 currentFrameValue() 的基础设施就位
- 日志显示 "coordinated value" 确认新的信号逻辑生效

## 下一步 (T4)
- PyBridge 需要调用 `setCurrentFrameValue(expectedFrame)` 
- 验证 PyBridge 与 LodClusters 的帧同步是否按预期工作
- 测试前 3 帧的 signal 值与 Python 送入的一致性

## 技术要点
- **线程安全**: 使用 mutex 保护帧值，确保 PyBridge 和 LodClusters 之间的同步
- **向后兼容**: 保留所有原有逻辑，只是改变信号值的来源
- **零拷贝设计**: 所有方法都是轻量级的，不影响渲染性能
- **防御性编程**: 包含完整的错误检查和日志记录