# Build Directories Structure

After cleanup, we now have a clean and organized build structure:

## 📁 Current Build Directories

### 1. `build/` - Main Application Build
- **Purpose**: Builds the main `vk_lod_clusters` executable
- **Output**: `_bin/Release/vk_lod_clusters`
- **Usage**: For standalone Vulkan application with GUI/headless modes
- **Configure**: 
  ```bash
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_DLSS=OFF
  ```
- **Build**: 
  ```bash
  cmake --build build --config Release -j4
  ```

### 2. `python/` - Python Extension Build  
- **Purpose**: Builds the `vk2torch_ext` Python extension for zero-copy pipeline
- **Output**: `python/_bin/Release/vk2torch_ext.cpython-310-x86_64-linux-gnu.so`
- **Size**: ~9.8MB (contains full 3D rendering pipeline)
- **Usage**: For Python→Vulkan→CUDA zero-copy integration
- **Configure**: 
  ```bash
  cd python
  cmake -S .. -B . -DCMAKE_TOOLCHAIN_FILE=../toolchains/system_no_conda.cmake \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_APP=OFF -DBUILD_PYTHON_EXT=ON \
    -DPython3_EXECUTABLE="$HOME/anaconda3/envs/vk2torch/bin/python"
  ```
- **Build**: 
  ```bash
  cmake --build . --config Release --target vk2torch_ext -j4
  ```

## 🧪 Testing the Python Extension

### Quick Test (Recommended):
```bash
# Activate conda environment
conda activate vk2torch

# Run simple test (tests import and methods)
python test_simple.py
```

### Advanced Test (Full Pipeline):
```bash
# Activate conda environment
conda activate vk2torch

# Run comprehensive test
PYTHONPATH="python/_bin/Release:$PYTHONPATH" python test_zero_copy_pipeline.py
```

## 🗂️ Removed Directories

The following build directories were cleaned up:
- `build_vk2torch/` - Old experimental builds
- `build-clean/` - Temporary clean builds
- `build_with_ipc/` - IPC test builds
- `build_clean/` - Duplicate clean builds
- `build-conda/` - Conda environment builds
- `build-py/` - Old Python builds

## 🎯 Key Files

### Python Extension:
- **Main Extension**: `python/_bin/Release/vk2torch_ext.cpython-310-x86_64-linux-gnu.so`
- **Test Scripts**: 
  - `test_simple.py` - Basic functionality test
  - `test_zero_copy_pipeline.py` - Comprehensive pipeline test

### Build Configuration:
- **Main CMakeLists.txt**: Root directory
- **Toolchain File**: `toolchains/system_no_conda.cmake`
- **Build Scripts**: `build_clean.sh`, `build_conda_fix.sh`

## 🚀 Usage Summary

1. **For Python Development**: Use `python/` build directory
2. **For C++ Development**: Use `build/` directory  
3. **Testing**: Run `python test_simple.py` from root directory
4. **Both builds can coexist** without conflicts