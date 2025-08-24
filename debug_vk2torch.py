#!/usr/bin/env python3
"""
Debug script for testing vk2torch_ext with absolute asset paths
"""

import sys
import pathlib
import os

# 获取仓库根目录
root = pathlib.Path(__file__).resolve().parent

# 添加Python扩展路径
sys.path.insert(0, str(root / 'build-py/_bin/Release'))

try:
    import vk2torch_ext
    print(f'✅ vk2torch_ext imported successfully')
    print(f'[test] using asset_root = {root}')
    
    # 测试使用绝对路径创建应用
    print(f'[test] Creating Vk2TorchApp with asset_root={root}')
    app = vk2torch_ext.Vk2TorchApp(512, 512, True, "house_new.glb", str(root))
    print('✅ Vk2TorchApp created successfully with absolute asset_root')

except ImportError as e:
    print(f'❌ Import failed: {e}')
    print('Make sure to build the Python extension first:')
    print('  conda activate vk2torch')
    print('  cd build-py && cmake --build . --config Release --target vk2torch_ext')
    
except Exception as e:
    print(f'❌ Runtime error: {e}')
    import traceback
    traceback.print_exc()