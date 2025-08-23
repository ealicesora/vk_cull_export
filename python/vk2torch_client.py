#!/usr/bin/env python3
"""
VK2Torch Client: Python integration for vk_lod_clusters via Unix Domain Sockets

This client connects to the Vulkan application, receives exported GPU resources via
file descriptor passing, and provides zero-copy access to rendered frames as PyTorch tensors.

Features:
- Unix Domain Socket communication with SCM_RIGHTS FD passing
- CUDA Driver API integration for external memory/semaphore import
- Zero-copy frame access via CuPy and PyTorch DLPack
- Camera parameter control and timeline synchronization
- PNG export functionality
"""

import os
import socket
import array
import json
import struct
import ctypes
import ctypes.util
import time
import numpy as np
from typing import Optional, Tuple, Dict, Any
import logging
import struct, numpy as np, socket
from multiprocessing import shared_memory


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import cupy as cp
    import torch
    HAS_CUPY = True
    HAS_TORCH = True
    logger.info("CuPy and PyTorch available")
except ImportError as e:
    logger.warning(f"CuPy/PyTorch not available: {e}")
    HAS_CUPY = False
    HAS_TORCH = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    logger.warning("OpenCV not available - PNG export will be limited")

# CUDA Driver API constants
CUDA_SUCCESS = 0
CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD = 1
CU_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD = 1




CUdeviceptr = ctypes.c_uint64  # 64-bit

class CUDA_EXTERNAL_MEMORY_BUFFER_DESC(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_uint64),
        ("size",   ctypes.c_uint64),
        ("flags",  ctypes.c_uint),
         ("reserved", ctypes.c_uint * 16) ,
    ]

class CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC(ctypes.Structure):
    class Handle(ctypes.Union):
        _fields_ = [
            ("fd", ctypes.c_int),
            ("win32", ctypes.c_void_p),  # Not used on Linux
            ("nvSciSyncObj", ctypes.c_void_p),  # Not used
        ]
    
    _fields_ = [
        ("type", ctypes.c_uint),
        ("handle", Handle),
        ("flags", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 16),
    ]
        

class _SigFence(ctypes.Structure):
    _fields_ = [
        ("value", ctypes.c_uint64),
        ("reserved", ctypes.c_uint * 16),   # ★ 必须有
    ]

class _SigKeyedMutex(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_uint),
        ("timeoutMs", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 14),   # 保持整体大小一致
    ]

class _SigParamsUnion(ctypes.Union):
    _fields_ = [("fence", _SigFence), ("keyedMutex", _SigKeyedMutex)]

class CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS(ctypes.Structure):
    _fields_ = [
        ("params", _SigParamsUnion),
        ("flags", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 16),
    ]

class _WaitFence(ctypes.Structure):
    _fields_ = [
        ("value", ctypes.c_uint64),
        ("reserved", ctypes.c_uint * 16),   # ★ 必须有
    ]

class _WaitKeyedMutex(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_uint),
        ("timeoutMs", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 14),
    ]

class _WaitParamsUnion(ctypes.Union):
    _fields_ = [("fence", _WaitFence), ("keyedMutex", _WaitKeyedMutex)]

class CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS(ctypes.Structure):
    _fields_ = [
        ("params", _WaitParamsUnion),
        ("flags", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 16),
    ]






CUdeviceptr = ctypes.c_uint64

class _Win32Pair(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_void_p),
        ("name",   ctypes.c_void_p),
    ]

class _HandleUnion(ctypes.Union):
    _fields_ = [
        ("fd", ctypes.c_int),
        ("win32", _Win32Pair),
        ("nvSciBufObject", ctypes.c_void_p),
    ]

class CUDA_EXTERNAL_MEMORY_HANDLE_DESC(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint),                 # CUexternalMemoryHandleType
        ("handle", _HandleUnion),
        ("size", ctypes.c_uint64),               # allocation size (NOT buffer size)
        ("flags", ctypes.c_uint),                # 0 or CUDA_EXTERNAL_MEMORY_DEDICATED
        ("reserved", ctypes.c_uint * 16) ,
    ]


CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD = 1
CUDA_SUCCESS = 0
CUDA_EXTERNAL_MEMORY_DEDICATED = 1



# Camera structure matching shaderio.h FrameConstants
class FrameConstants(ctypes.Structure):
    """
    Camera constants structure matching shaderio.h FrameConstants.
    Only includes essential camera parameters for simplicity.
    """
    _fields_ = [
        # 4x4 matrices (16 floats each)
        ("projMatrix", ctypes.c_float * 16),
        ("projMatrixI", ctypes.c_float * 16), 
        ("viewProjMatrix", ctypes.c_float * 16),
        ("viewProjMatrixI", ctypes.c_float * 16),
        ("viewMatrix", ctypes.c_float * 16),
        ("viewMatrixI", ctypes.c_float * 16),
        # vec4 (4 floats each)
        ("viewPos", ctypes.c_float * 4),
        ("viewDir", ctypes.c_float * 4),
        ("viewPlane", ctypes.c_float * 4),
        # More matrices and parameters...
        ("skyProjMatrixI", ctypes.c_float * 16),
        ("viewProjMatrixPrev", ctypes.c_float * 16),
        # viewport and other params
        ("viewport", ctypes.c_int32 * 2),
        ("viewportf", ctypes.c_float * 2),
        ("viewPixelSize", ctypes.c_float * 2),
        ("viewClipSize", ctypes.c_float * 2),
        ("jitter", ctypes.c_float * 2),
        ("_pad", ctypes.c_float * 2),
        ("wLightPos", ctypes.c_float * 3),
        ("lightMixer", ctypes.c_float),
        ("wUpDir", ctypes.c_float * 3),
        ("sceneSize", ctypes.c_float),
        ("wMirrorBox", ctypes.c_float * 4),
        ("flipWinding", ctypes.c_uint32),
        ("useMirrorBox", ctypes.c_uint32),
        ("visualize", ctypes.c_uint32),
        ("fov", ctypes.c_float),
        ("nearPlane", ctypes.c_float),
        ("farPlane", ctypes.c_float),
        ("ambientOcclusionRadius", ctypes.c_float),
        ("ambientOcclusionSamples", ctypes.c_int32),
        ("hizSizeFactors", ctypes.c_float * 4),
        ("nearSizeFactors", ctypes.c_float * 4),
        ("hizSizeMax", ctypes.c_float),
        ("facetShading", ctypes.c_int32),
        ("supersample", ctypes.c_int32),
    ]

class CUDADriverAPI:
    """CUDA Driver API wrapper for external memory/semaphore operations."""
    
    def __init__(self):
        self.cuda = None
        self.context = None
        self.stream = None
        self._load_cuda()
    


    def cu_check(self, code, where=""):
        if code != 0:
            # cuGetErrorString
            try:
                errStr = ctypes.c_char_p()
                self.cuda.cuGetErrorString(ctypes.c_int(code), ctypes.byref(errStr))
                msg = errStr.value.decode() if errStr.value else "Unknown"
            except Exception:
                msg = "Unknown"
            raise RuntimeError(f"{where} failed: {code} ({msg})")

    def _load_cuda(self):
        """Load CUDA driver library and setup function pointers."""
        libcuda_name = ctypes.util.find_library('cuda')
        if not libcuda_name:
            # Try common paths
            for path in ['/usr/local/cuda/lib64/libcuda.so', '/usr/lib/x86_64-linux-gnu/libcuda.so']:
                if os.path.exists(path):
                    libcuda_name = path
                    break
                    
        if not libcuda_name:
            raise RuntimeError("CUDA driver library not found")
            
        self.cuda = ctypes.CDLL(libcuda_name)
        logger.info(f"Loaded CUDA driver: {libcuda_name}")
        
        # Define function prototypes for external memory functions
        # These may not be available in older CUDA versions, so we check first
        try:
            self.cuda.cuImportExternalMemory.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            self.cuda.cuImportExternalMemory.restype = ctypes.c_int
            
            self.cuda.cuExternalMemoryGetMappedBuffer.restype  = ctypes.c_int
            self.cuda.cuExternalMemoryGetMappedBuffer.argtypes = [
                ctypes.POINTER(CUdeviceptr),              # CUdeviceptr* pDevice
                ctypes.c_void_p,                          # CUexternalMemory extMem
                ctypes.POINTER(CUDA_EXTERNAL_MEMORY_BUFFER_DESC)  # const desc*
            ]
            self.cuda.cuImportExternalSemaphore.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC)]
            self.cuda.cuImportExternalSemaphore.restype = ctypes.c_int
            
            self.cuda.cuSignalExternalSemaphoresAsync.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS), ctypes.c_uint, ctypes.c_void_p]
            self.cuda.cuSignalExternalSemaphoresAsync.restype = ctypes.c_int
            
            self.cuda.cuWaitExternalSemaphoresAsync.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS), ctypes.c_uint, ctypes.c_void_p]
            self.cuda.cuWaitExternalSemaphoresAsync.restype = ctypes.c_int
            
            # Add UUID function
            self.cuda.cuDeviceGetUuid.argtypes = [ctypes.POINTER(ctypes.c_ubyte * 16), ctypes.c_int]
            self.cuda.cuDeviceGetUuid.restype = ctypes.c_int
            
            # Add device count function
            self.cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
            self.cuda.cuDeviceGetCount.restype = ctypes.c_int
        except AttributeError as e:
            logger.warning(f"Some CUDA external memory functions not available: {e}")
        
        # Initialize CUDA
        result = self.cuda.cuInit(0)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuInit failed: {result}")
        
        # Don't create context yet - wait until we know which device to use
        self.context = None
        
        # Don't create stream yet - wait until context is created
        self.stream = None
        
        logger.info("CUDA driver initialized (context not created yet)")
    
    def find_device_by_uuid(self, target_uuid_hex: str) -> int:
        """Find CUDA device matching the given UUID hex string."""
        # Get device count
        device_count = ctypes.c_int()
        result = self.cuda.cuDeviceGetCount(ctypes.byref(device_count))
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuDeviceGetCount failed: {result}")
        
        logger.info(f"Found {device_count.value} CUDA device(s)")
        
        # Convert hex string to bytes for comparison
        target_uuid_bytes = bytes.fromhex(target_uuid_hex)
        
        # Check each device
        for i in range(device_count.value):
            # Get device UUID
            uuid_bytes = (ctypes.c_ubyte * 16)()
            result = self.cuda.cuDeviceGetUuid(uuid_bytes, i)
            if result != CUDA_SUCCESS:
                logger.warning(f"Failed to get UUID for device {i}: {result}")
                continue
            
            # Convert to bytes for comparison
            device_uuid = bytes(uuid_bytes)
            device_uuid_hex = device_uuid.hex()
            
            logger.info(f"  Device {i} UUID: {device_uuid_hex}")
            
            if device_uuid == target_uuid_bytes:
                logger.info(f"  ✓ Matched! Using CUDA device {i}")
                return i
        
        # No match found
        raise RuntimeError(f"No CUDA device found matching UUID: {target_uuid_hex}")
    
    def create_context_on_device(self, device_id: int):
        """Create CUDA context on specific device."""
        if self.context:
            logger.warning("Context already exists")
            return
            
        ctx = ctypes.c_void_p()
        result = self.cuda.cuCtxCreate_v2(ctypes.byref(ctx), 0, device_id)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuCtxCreate on device {device_id} failed: {result}")
        
        self.context = ctx
        logger.info(f"Created CUDA context on device {device_id}")
        
        # Now create stream
        stream = ctypes.c_void_p()
        result = self.cuda.cuStreamCreate(ctypes.byref(stream), 0)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuStreamCreate failed: {result}")
        self.stream = stream
        logger.info("CUDA stream created")
        
    # def get_mapped_buffer(self, ext_mem, size: int, name: str) -> ctypes.c_void_p:
    #     assert ext_mem and ext_mem.value, f"Invalid external memory for {name}"
    #     desc = CUDA_EXTERNAL_MEMORY_BUFFER_DESC()
    #     ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
    #     desc.offset = 0
    #     desc.size   = ctypes.c_ulonglong(size)  # 来自握手 JSON 的 *_bytes
    #     desc.flags  = 0
    #     dev_ptr = CUdeviceptr(0)
    #     err = self.cuda.cuExternalMemoryGetMappedBuffer(ctypes.byref(dev_ptr), ext_mem, ctypes.byref(desc))
    #     self.cu_check(err, f"cuExternalMemoryGetMappedBuffer({name})")
    #     return dev_ptr
        
    def get_mapped_buffer(self, ext_mem: ctypes.c_void_p, size: int, name: str) -> ctypes.c_void_p:
        desc = CUDA_EXTERNAL_MEMORY_BUFFER_DESC()
        ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
        desc.offset = 0
        desc.size   = ctypes.c_ulonglong(size)       # ★ ≤ import 时的 desc.size
        desc.flags  = 0                               # ★ 必须为 0
        dev_ptr = CUdeviceptr(0)
        err = self.cuda.cuExternalMemoryGetMappedBuffer(ctypes.byref(dev_ptr), ext_mem, ctypes.byref(desc))
        if err != CUDA_SUCCESS:
            self.cu_check(err,"get_mapped_buffer")
            raise RuntimeError(f"cuExternalMemoryGetMappedBuffer({name}) failed: {err} (invalid argument)")

        return dev_ptr


        
    def import_external_semaphore(self, fd: int) -> ctypes.c_void_p:
        """Import external semaphore from file descriptor."""
        # Define CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC structure

        # Create and populate descriptor
        desc = CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
        ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
        desc.type = 9
        desc.handle.fd = fd
        desc.flags = 0x00 #0x01  # CUDA_EXTERNAL_SEMAPHORE_HANDLE_FLAG_TIMELINE_SEMAPHORE
        
        # Import external semaphore
        ext_sem = ctypes.c_void_p()
        result = self.cuda.cuImportExternalSemaphore(ctypes.byref(ext_sem), ctypes.byref(desc))
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuImportExternalSemaphore failed: {result}")
        return ext_sem
        


    def import_external_memory(self, fd: int, size: int, *, dedicated: bool=True) -> ctypes.c_void_p:
        # self.cuda.cuImportExternalMemory.restype  = ctypes.c_int
        # self.cuda.cuImportExternalMemory.argtypes = [
        #     ctypes.POINTER(ctypes.c_void_p),
        #     ctypes.POINTER(CUDA_EXTERNAL_MEMORY_HANDLE_DESC)
        # ]

        # print(ctypes.sizeof(CUDA_EXTERNAL_MEMORY_HANDLE_DESC))
        # print(ctypes.sizeof(CUDA_EXTERNAL_MEMORY_BUFFER_DESC))

        desc = CUDA_EXTERNAL_MEMORY_HANDLE_DESC()
        ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))
        desc.type = CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD
        desc.handle.fd = fd
        desc.size = ctypes.c_ulonglong(size)         # ★ 传 Vulkan 实际分配的大小
        desc.flags = CUDA_EXTERNAL_MEMORY_DEDICATED if dedicated else 0
        ext_mem = ctypes.c_void_p()
        err = self.cuda.cuImportExternalMemory(ctypes.byref(ext_mem), ctypes.byref(desc))
        if err != CUDA_SUCCESS:
            raise RuntimeError(f"cuImportExternalMemory failed: {err} (fd={fd}, size={size}, dedicated={dedicated})")
        return ext_mem
            

    def signal_semaphore(self, semaphore, value:int, stream=None):
        if stream is None: stream = self.stream
        params = CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS()
        ctypes.memset(ctypes.byref(params), 0, ctypes.sizeof(params))

        params.params.fence.value = ctypes.c_uint64(value)     # ★ 关键

        params.flags = 0
  
        err = self.cuda.cuSignalExternalSemaphoresAsync(
            (ctypes.c_void_p * 1)(semaphore),
            (CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS * 1)(params),
            1,
            stream if stream is not None else ctypes.c_void_p(0),
        )

        if err != CUDA_SUCCESS:
            self.cu_check(err,"signal_semaphore")
            raise RuntimeError(f"cuSignalExternalSemaphoresAsync failed: {err}")

        # self.synchronize_stream(stream)

    def wait_semaphore(self, semaphore: ctypes.c_void_p, value: int, stream: Optional[ctypes.c_void_p] = None):
        """Wait for external semaphore timeline value."""
        if stream is None:
            stream = self.stream
        
        params = CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS()
        ctypes.memset(ctypes.byref(params), 0, ctypes.sizeof(params))
        params.params.fence.value = ctypes.c_uint64(value)
        params.flags = 0
        
        result = self.cuda.cuWaitExternalSemaphoresAsync(
            (ctypes.c_void_p * 1)(semaphore),                 # 数组
            (CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS * 1)(params),
            1,
            stream if stream is not None else ctypes.c_void_p(0),
        )

        if result != CUDA_SUCCESS:
            self.cu_check(result,"cuWaitExternalSemaphoresAsync")
            raise RuntimeError(f"cuWaitExternalSemaphoresAsync failed: {result}")
       

    def synchronize_stream(self, stream: Optional[ctypes.c_void_p] = None):
        """Synchronize CUDA stream."""
        if stream is None:
            stream = self.stream
        result = self.cuda.cuStreamSynchronize(stream)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuStreamSynchronize failed: {result}")
            
    def memcpy_host_to_device(self, dst: ctypes.c_void_p, src: ctypes.c_void_p, size: int):
        """Copy from host to device memory."""
        result = self.cuda.cuMemcpyHtoD_v2(dst, src, size)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuMemcpyHtoD failed: {result}")

class VK2TorchClient:
    """Main client class for VK to PyTorch integration."""
    
    def __init__(self, socket_path: str = "/tmp/vk2torch.sock"):
        self.socket_path = socket_path
        self.socket = None
        self.connected = False
        
        # Shared memory for camera matrices
        self.shm = None
        self.shm_name = 'py2vk_cam32f'
        self.shm_size = 256
        self.shm_seq_offset = 0
        self.shm_data_offset = 64


        # Handshake data
        self.width = 0
        self.height = 0
        self.format = ""
        self.color_readback_bytes = 0
        self.row_pitch = 0
        self.cam_bytes = 0
        self.vk_uuid = None
        self.cam_dedicated = False
        self.color_dedicated = False
        
        # CUDA resources
        self.cuda_api = None
        self.dev_cam = None
        self.dev_color = None
        self.ext_mem_cam = None
        self.ext_mem_color = None
        self.sem_cam = None
        self.sem_done = None
        
        # Frame counter
        self.frame_number = 1
        
        # Initialize CUDA if available
        if HAS_CUPY and HAS_TORCH:
            print('having both HAS_CUPY and HAS_TORCH')
            try:
                self.cuda_api = CUDADriverAPI()
                logger.info("CUDA Driver API initialized")
                print(type(self.cuda_api))
            except Exception as e:
                logger.error(f"Failed to initialize CUDA: {e}")
                self.cuda_api = None
        
    def connect(self) -> bool:
        """Connect to Vulkan application via UDS."""
        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(self.socket_path)
            logger.info(f"Connected to Vulkan app at {self.socket_path}")
            
            # Perform handshake
            if not self._handshake():
                return False
            
            # Wait for ready message from Vulkan
            if not self._wait_for_ready():
                return False
                
            self.connected = True
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
            
    def _handshake(self) -> bool:
        """Perform handshake with Vulkan application."""
        try:
            # Receive JSON header size
            json_size_data = self.socket.recv(4)
            if len(json_size_data) != 4:
                logger.error("Failed to receive JSON size")
                return False
                
            json_size = struct.unpack('I', json_size_data)[0]
            logger.info(f"Expecting JSON of size {json_size}")
            
            # Receive JSON data
            json_data = self.socket.recv(json_size)
            if len(json_data) != json_size:
                logger.error("Failed to receive complete JSON")
                return False
                
            # Parse handshake info
            handshake = json.loads(json_data.decode())
            self.width = handshake['w']
            self.height = handshake['h']
            self.format = handshake['format']
            self.color_readback_bytes = handshake['color_readback_bytes']
            self.row_pitch = handshake['row_pitch']
            self.cam_bytes = handshake['cam_bytes']
            self.vk_uuid = handshake.get('vk_uuid', None)
            self.cam_dedicated = handshake.get('cam_dedicated', False)
            self.color_dedicated = handshake.get('color_dedicated', False)
            
            logger.info(f"Handshake: {self.width}x{self.height} {self.format}, "
                       f"color={self.color_readback_bytes} bytes, cam={self.cam_bytes} bytes")
            if self.vk_uuid:
                logger.info(f"Vulkan GPU UUID: {self.vk_uuid}")
            logger.info(f"Dedicated allocation: cam={self.cam_dedicated}, color={self.color_dedicated}")
            print('sleep for 3s for device to get ready')
            time.sleep(3)
            # Receive file descriptors
            if not self._receive_fds():
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Handshake failed: {e}")
            return False
            
    def _receive_fds(self) -> bool:
        """Receive file descriptors via SCM_RIGHTS."""
        try:
            # Prepare to receive message with control data
            msg = b'x'  # Dummy data
            fds = array.array("i")   # Array to hold received file descriptors
            
            # Receive message with ancillary data
            msg_data, ancdata, flags, addr = self.socket.recvmsg(len(msg), socket.CMSG_SPACE(4 * 4))
            
            # Extract file descriptors from ancillary data
            for cmsg_level, cmsg_type, cmsg_data in ancdata:
                if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                    # Unpack file descriptors
                    fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
                    
            if len(fds) != 4:
                logger.error(f"Expected 4 FDs, got {len(fds)}")
                return False
                
            cam_fd, color_fd, cam_sem_fd, done_sem_fd = fds
            
            # Log the FDs received on Python side
            logger.info("=== PYTHON SIDE: Received FDs ===")
            logger.info(f"  Camera Memory FD:    {cam_fd}")
            logger.info(f"  Color Memory FD:     {color_fd}")
            logger.info(f"  Camera Semaphore FD: {cam_sem_fd}")
            logger.info(f"  Done Semaphore FD:   {done_sem_fd}")
            logger.info("==================================")
            print(os.readlink(f"/proc/{os.getpid()}/fd/{cam_fd}"))

            # Import external memory and semaphores via CUDA
            if self.cuda_api:
                try:


                    
                    # First, find and select the correct CUDA device by UUID
                    if self.vk_uuid:
                        logger.info("Matching CUDA device with Vulkan UUID...")
                        device_id = self.cuda_api.find_device_by_uuid(self.vk_uuid)
                        self.cuda_api.create_context_on_device(device_id)
                        
                    else:
                        logger.warning("No UUID from Vulkan, using default device 0")
                        self.cuda_api.create_context_on_device(0)



                    self.sem_cam = self.cuda_api.import_external_semaphore(cam_sem_fd)
                    self.sem_done = self.cuda_api.import_external_semaphore(done_sem_fd)
                    
                    # Optional: Test semaphore functionality immediately
                    if os.environ.get('VK2TORCH_TEST_SEMAPHORE', '0') == '1':
                        self._test_semaphore_sync()
                    
                    # Use the dedicated flags from handshake
                    self.ext_mem_color = self.cuda_api.import_external_memory(color_fd, self.color_readback_bytes, dedicated=self.color_dedicated)
                    self.dev_color = self.cuda_api.get_mapped_buffer(self.ext_mem_color, self.color_readback_bytes, "color")

                    self.ext_mem_cam = self.cuda_api.import_external_memory(cam_fd, self.cam_bytes, dedicated=self.cam_dedicated)
                    self.dev_cam = self.cuda_api.get_mapped_buffer(self.ext_mem_cam, self.cam_bytes, "cam")
                    # Now import external memory
                    

                    
       

                    logger.info("CUDA external resources imported successfully")
                except Exception as cuda_error:
                    logger.warning(f"CUDA import failed: {cuda_error}")
                    logger.warning("Connection will continue without CUDA functionality")
                    logger.warning("You can still test connection but cannot get frame data")
                    
                    # Disable CUDA for this session
                    self.cuda_api = None
                    self.ext_mem_cam = None
                    self.ext_mem_color = None
                    self.dev_cam = None
                    self.dev_color = None
                    self.sem_cam = None
                    self.sem_done = None
                    for fd in fds:
                        print(fd)
                        os.close(fd)          
                    
            # Close file descriptors (CUDA has taken ownership)

                
            return True
            
        except Exception as e:
            logger.error(f"Failed to receive FDs: {e}")
            return False
    
    def _wait_for_ready(self) -> bool:
        """Wait for ready message from Vulkan."""
        try:
            # Receive JSON header size
            json_size_data = self.socket.recv(4)
            if len(json_size_data) != 4:
                logger.error("Failed to receive ready message size")
                return False
                
            json_size = struct.unpack('I', json_size_data)[0]
            logger.info(f"Expecting ready message of size {json_size}")
            
            # Receive JSON data
            json_data = self.socket.recv(json_size)
            if len(json_data) != json_size:
                logger.error("Failed to receive complete ready message")
                return False
                
            # Parse ready message
            ready_msg = json.loads(json_data.decode())
            if ready_msg.get('type') != 'ready_to_render':
                logger.error(f"Expected ready_to_render message, got: {ready_msg}")
                return False
            
            logger.info(f"✅ Received ready message from Vulkan: frame={ready_msg.get('frame', 0)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to wait for ready message: {e}")
            return False
            
    def _init_shared_memory(self) -> bool:
        """Initialize shared memory for camera matrices."""
        try:
            # Try to create new shared memory
            self.shm = shared_memory.SharedMemory(
                name=self.shm_name, 
                create=True, 
                size=self.shm_size
            )
            logger.info(f"Created shared memory: {self.shm_name}")
            # Initialize with zeros
            self.shm.buf[:] = b'\x00' * self.shm_size
        except FileExistsError:
            # Shared memory already exists, open it
            try:
                self.shm = shared_memory.SharedMemory(name=self.shm_name, create=False)
                logger.info(f"Opened existing shared memory: {self.shm_name}")
            except FileNotFoundError:
                logger.error(f"Shared memory {self.shm_name} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize shared memory: {e}")
            return False
        
        return True
    
    def _write_camera_to_shm(self, view_matrix: np.ndarray, proj_matrix: np.ndarray) -> bool:
        """Write camera matrices to shared memory using seqlock protocol."""
        if not self.shm:
            return False
            
        try:
            # Combine view and proj matrices into 32 float32 array
            view_arr = np.asarray(view_matrix, dtype=np.float32).flatten()[:16]
            proj_arr = np.asarray(proj_matrix, dtype=np.float32).flatten()[:16]
            
            if len(view_arr) != 16 or len(proj_arr) != 16:
                logger.error("View and projection matrices must have 16 elements each")
                return False
            
            camera_data = np.concatenate([view_arr, proj_arr])
            
            # Get sequence counter for seqlock protocol
            seq_view = memoryview(self.shm.buf)[self.shm_seq_offset:self.shm_seq_offset + 8]
            data_view = memoryview(self.shm.buf)[self.shm_data_offset:self.shm_data_offset + 128]
            
            # Read current sequence 
            seq = struct.unpack('<Q', seq_view)[0]
            
            # Step 1: Increment sequence to odd (writing state)
            seq += 1
            struct.pack_into('<Q', self.shm.buf, self.shm_seq_offset, seq)
            
            # Step 2: Write the data
            data_view[:] = camera_data.tobytes()
            
            # Step 3: Increment sequence to even (stable state)  
            seq += 1
            struct.pack_into('<Q', self.shm.buf, self.shm_seq_offset, seq)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to write camera data to shared memory: {e}")
            return False

    def update_camera(self, view_matrix: np.ndarray, proj_matrix: np.ndarray) -> bool:
        if not self.connected:
            return False
        try:
            # Initialize shared memory if not already done
            if not self.shm and not self._init_shared_memory():
                logger.warning("Shared memory not available - this may cause camera update to fail")
                return False
            
            # Write camera matrices to shared memory using seqlock protocol
            if not self._write_camera_to_shm(view_matrix, proj_matrix):
                logger.error("Failed to write camera matrices to shared memory")
                return False
            
            # Signal camera ready via semaphore (maintaining frame sync)
            if self.cuda_api:
                self.cuda_api.signal_semaphore(self.sem_cam, self.frame_number)
                # self.frame_number += 1
            else:
                logger.warning("CUDA API not available - semaphore signaling disabled")
            
            return True
        except Exception as e:
            logger.error(f"Failed to update camera: {e}")
            return False



    def get_frame(self, timeout_ms: int = 5000) -> Optional['torch.Tensor']:
        """Get rendered frame as PyTorch tensor (zero-copy)."""
        if not self.connected:
            logger.error("Not connected to Vulkan app")
            return None
        
        if not self.cuda_api:
            logger.warning("CUDA functionality not available - cannot get frame data")
            logger.info("This could be due to CUDA import failure during connection")
            logger.info("Connection is still active for testing purposes")
            return None
            
        if not HAS_CUPY or not HAS_TORCH:
            logger.error("CuPy or PyTorch not available")
            return None
            
        try:
            # Wait for frame completion
            self.cuda_api.synchronize_stream()
            self.cuda_api.wait_semaphore(self.sem_done, self.frame_number)
 
            self.cuda_api.synchronize_stream()
            # return None

            umem = cp.cuda.UnownedMemory(
                int(self.dev_color.value), 
                self.color_readback_bytes, 
                owner=None
            )
            mptr = cp.cuda.MemoryPointer(umem, 0)
            
            # Create properly strided array for row-pitch alignment
            # cupy_array = cp.ndarray(
            #     (self.height, self.width, 4),
            #     dtype=cp.uint8,
            #     memptr=mptr,
            #     strides=(self.row_pitch, 4, 1)
            # )
            H, W = self.height, self.width

            raw32 = cp.ndarray((H, W), dtype=cp.uint32, memptr=mptr,
                            strides=(self.row_pitch, 4))  # (row_pitch_bytes, bytes_per_pixel)

            # 2) 仅“视图”改成 int32（零拷，方便 Torch 接收；不要再用 raw32 参与 DLPack）
            raw_i32 = raw32.view(cp.int32)

            # 3) 零拷到 Torch（注意：from_dlpack 接管内存生命周期；之后别再用 raw_i32）
            t_i32 = torch.from_dlpack(raw_i32)

            # 4) Torch 端完成位运算与归一化（尽量链式，减少中间张量）
            mask = 0x00FFFFFF
            torch_tensor = (t_i32 & mask).to(torch.float32) * (1.0 / 16777215.0) 
            # torch_tensor = torch.from_dlpack(depth01)

            # torch_tensor = torch.utils.dlpack.from_dlpack(depth01.toDlpack())
            # print(torch_tensor.device)
            
            # Convert to PyTorch tensor via DLPack (zero-copy)
            # torch_tensor = torch.utils.dlpack.from_dlpack(torch_depth.toDlpack())
            # print(torch_tensor.shape)
            # print(torch_tensor.sum())
            # Increment frame counter for next frame
            self.frame_number += 1
            # print(torch_tensor)
            return torch_tensor
            
        except Exception as e:
            logger.error(f"Failed to get frame: {e}")
            return None


    def save_depth_png(
        self,
        depth,                  # torch.Tensor 或 numpy.ndarray，形状可为 (H,W), (1,H,W), (H,W,1)
        filename: str,
        *,
        normalize: bool = True,
        min_val: float | None = None,
        max_val: float | None = None,
        invert: bool = False,           # 若你用 reversed-Z（近=大），想让“近更亮”，可设 True
        robust_percentile: float = 0.5, # 百分位裁剪，0.5 表示 [0.5%, 99.5%]
        bitdepth: int = 16              # 16 或 8；建议 16
    ) -> bool:
        """
        将单通道深度保存为 PNG。返回 True/False 表示是否保存成功。
        - normalize=True 时：用 (min,max) 将深度线性映射到 [0,1]（会先按百分位裁剪减少异常值影响）。
        - min_val/max_val 可手动覆盖自动范围。
        - invert=True 则做 1 - x（常用于 reversed-Z: 近=大，想让近=亮）。
        - bitdepth: 16（推荐）或 8。
        """
        try:
            import numpy as np
            # 尽量用已存在的环境变量/对象
            has_cv = globals().get("HAS_OPENCV", False)
            if has_cv:
                import cv2
            else:
                cv2 = None

            # 1) 拿到 numpy，去掉多余维度
            if "torch" in str(type(depth)):  # 粗略判断是否为 torch.Tensor
                # 防止梯度/显存问题
                depth_np = depth.detach().to("cpu").numpy()
            else:
                depth_np = np.asarray(depth)

            # squeeze 到 (H,W)
            if depth_np.ndim == 3:
                # 允许 [1,H,W] 或 [H,W,1]
                if depth_np.shape[0] == 1:
                    depth_np = depth_np[0]
                elif depth_np.shape[2] == 1:
                    depth_np = depth_np[:, :, 0]
                else:
                    raise ValueError(f"Depth tensor must be single-channel; got shape {depth_np.shape}")
            elif depth_np.ndim != 2:
                raise ValueError(f"Depth tensor must be 2D or single-channel 3D; got ndim={depth_np.ndim}")

            depth_np = np.asanyarray(depth_np).astype(np.float32, copy=False)

            # 2) 处理 NaN/Inf
            finite_mask = np.isfinite(depth_np)
            if not np.any(finite_mask):
                if 'logger' in globals():
                    logger.error("Depth has no finite values.")
                return False

            # 3) 计算归一化范围
            lo, hi = (min_val, max_val)
            if normalize:
                vals = depth_np[finite_mask]
                # 百分位裁剪（减少极端值影响）
                p = float(robust_percentile)
                if lo is None:
                    lo = np.percentile(vals, p) if p > 0 else float(np.min(vals))
                if hi is None:
                    hi = np.percentile(vals, 100.0 - p) if p > 0 else float(np.max(vals))
            else:
                # 不做归一化就直接 clamp 到 [0,1]
                lo = 0.0 if lo is None else lo
                hi = 1.0 if hi is None else hi

            # 防止 lo==hi
            if hi <= lo:
                # 退化情况：全图近似常数
                if 'logger' in globals():
                    logger.warning(f"Depth range collapsed (lo={lo}, hi={hi}), producing a constant image.")
                norm = np.zeros_like(depth_np, dtype=np.float32)
            else:
                norm = (depth_np - lo) / (hi - lo)

            # 4) 反转（常用于 reversed-Z：近=大 → 近更亮）
            if invert:
                norm = 1.0 - norm

            # 5) 裁剪到 [0,1]，并将非有限值置 0
            norm[~finite_mask] = 0.0
            norm = np.clip(norm, 0.0, 1.0)

            # 6) 转整数并保存
            if bitdepth == 16:
                img = np.round(norm * 65535.0).astype(np.uint16)
            elif bitdepth == 8:
                img = np.round(norm * 255.0).astype(np.uint8)
            else:
                raise ValueError("bitdepth must be 8 or 16")

            # OpenCV 保存（shape 必须是 (H,W)）
            if has_cv and cv2 is not None:
                ok = cv2.imwrite(filename, img)
                if ok:
                    if 'logger' in globals():
                        logger.info(f"Saved depth to {filename} ({bitdepth}-bit PNG)")
                    return True
            else:
                # PIL 兜底
                try:
                    from PIL import Image
                    if bitdepth == 16:
                        pil_img = Image.fromarray(img, mode="I;16")
                    else:
                        pil_img = Image.fromarray(img, mode="L")
                    pil_img.save(filename)
                    if 'logger' in globals():
                        logger.info(f"Saved depth to {filename} using PIL ({bitdepth}-bit)")
                    return True
                except ImportError:
                    if 'logger' in globals():
                        logger.error("No image library available (OpenCV or PIL)")
                    return False

            return False

        except Exception as e:
            if 'logger' in globals():
                logger.error(f"Failed to save depth PNG: {e}")
            return False


    def save_frame_png(self, tensor: 'torch.Tensor', filename: str) -> bool:
        """Save frame tensor as PNG file."""
        try:
            # Convert to CPU and numpy
            if tensor.is_cuda:
                tensor_cpu = tensor.cpu()
            else:
                tensor_cpu = tensor
                
            # Convert to numpy array
            np_array = tensor_cpu.numpy()
            
            # Convert RGBA to BGR for OpenCV (drop alpha)
            if np_array.shape[2] == 4:
                bgr_array = np_array[:, :, :3]  # Drop alpha
                bgr_array = bgr_array[:, :, [2, 1, 0]]  # RGB to BGR
            else:
                bgr_array = np_array
                
            if HAS_OPENCV:
                # Use OpenCV to save
                success = cv2.imwrite(filename, bgr_array)
                if success:
                    logger.info(f"Saved frame to {filename}")
                    return True
            else:
                # Fallback using PIL or similar
                try:
                    from PIL import Image
                    if bgr_array.shape[2] == 3:
                        # Convert BGR back to RGB for PIL
                        rgb_array = bgr_array[:, :, [2, 1, 0]]
                        image = Image.fromarray(rgb_array, 'RGB')
                    else:
                        image = Image.fromarray(bgr_array)
                    image.save(filename)
                    logger.info(f"Saved frame to {filename} using PIL")
                    return True
                except ImportError:
                    logger.error("No image library available (OpenCV or PIL)")
                    
            return False
            
        except Exception as e:
            logger.error(f"Failed to save PNG: {e}")
            return False
            
    def _test_semaphore_sync(self):
        """Test semaphore synchronization immediately after import."""
        logger.info("=== SEMAPHORE SYNC TEST ===")
        try:
            # Signal camera semaphore with value 42
            test_value = 42
            logger.info(f"Signaling camera semaphore with value {test_value}...")
            self.cuda_api.signal_semaphore(self.sem_cam, test_value)
            logger.info("✓ Signal sent successfully")
            
            # Wait for the same value on done semaphore (Vulkan should echo it back)
            logger.info(f"Waiting for done semaphore value {test_value}...")
            start_time = time.time()
            self.cuda_api.wait_semaphore(self.sem_done, test_value)
            self.cuda_api.synchronize_stream()
            wait_time = (time.time() - start_time) * 1000
            
            logger.info(f"✓ Semaphore wait completed in {wait_time:.1f}ms")
            logger.info("✓ SEMAPHORE SYNC TEST PASSED!")
            
            # Reset frame counter since we used value 42
            self.frame_number = 43
            
        except Exception as e:
            logger.error(f"✗ Semaphore test failed: {e}")
            logger.warning("Continuing without semaphore sync...")
    

    def disconnect(self):
        """Disconnect from Vulkan application."""
        # Close shared memory
        if self.shm:
            try:
                self.shm.close()
                self.shm.unlink()
                logger.info("Closed shared memory")
            except Exception as e:
                logger.warning(f"Error closing shared memory: {e}")
            self.shm = None
        
        if self.socket:
            self.socket.close()
            self.socket = None
        self.connected = False
        logger.info("Disconnected from Vulkan app")
    
    @property
    def has_cuda_support(self) -> bool:
        """Check if CUDA functionality is available for this connection."""
        print("self.cuda_api",self.cuda_api)
        print("self.connected",self.connected)
        return self.connected and self.cuda_api is not None
    
    @property
    def connection_status(self) -> str:
        """Get detailed connection status."""
        if not self.connected:
            return "Not connected"
        elif not self.cuda_api:
            return "Connected (CUDA unavailable - testing mode only)"
        else:
            return "Connected (Full functionality)"
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
