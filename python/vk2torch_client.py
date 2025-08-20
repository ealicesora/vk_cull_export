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




class CUDA_EXTERNAL_MEMORY_HANDLE_DESC(ctypes.Structure):
    class Handle(ctypes.Union):
        _fields_ = [("fd", ctypes.c_int),
                    ("win32", ctypes.c_void_p),
                    ("nvSciBufObject", ctypes.c_void_p)]
    _anonymous_ = ("handle",)
    _fields_ = [("type", ctypes.c_uint),
                ("handle", Handle),
                ("size", ctypes.c_ulonglong),
                ("flags", ctypes.c_uint),
                ("reserved", ctypes.c_uint * 16)]

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
            
            self.cuda.cuExternalMemoryGetMappedBuffer.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p]
            self.cuda.cuExternalMemoryGetMappedBuffer.restype = ctypes.c_int
            
            self.cuda.cuImportExternalSemaphore.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            self.cuda.cuImportExternalSemaphore.restype = ctypes.c_int
            
            self.cuda.cuSignalExternalSemaphoresAsync.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
            self.cuda.cuSignalExternalSemaphoresAsync.restype = ctypes.c_int
            
            self.cuda.cuWaitExternalSemaphoresAsync.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
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
        
        
    def get_mapped_buffer(self, ext_mem: ctypes.c_void_p, size: int) -> ctypes.c_void_p:
        """Get device pointer from external memory."""
        # Define CUDA_EXTERNAL_MEMORY_BUFFER_DESC structure
        class CUDA_EXTERNAL_MEMORY_BUFFER_DESC(ctypes.Structure):
            _fields_ = [
                ("offset", ctypes.c_ulonglong),
                ("size", ctypes.c_ulonglong),
                ("flags", ctypes.c_uint),
                ("reserved", ctypes.c_uint * 16),
            ]
        
        # Create and populate descriptor
        desc = CUDA_EXTERNAL_MEMORY_BUFFER_DESC()
        desc.offset = 0
        desc.size = size
        desc.flags = 0
        
        # Get mapped buffer
        dev_ptr = ctypes.c_void_p()
        result = self.cuda.cuExternalMemoryGetMappedBuffer(ctypes.byref(dev_ptr), ext_mem, ctypes.byref(desc))
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuExternalMemoryGetMappedBuffer failed: {result}")
            
        return dev_ptr
        
    def import_external_semaphore(self, fd: int) -> ctypes.c_void_p:
        """Import external semaphore from file descriptor."""
        # Define CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC structure
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
        
        # Create and populate descriptor
        desc = CUDA_EXTERNAL_SEMAPHORE_HANDLE_DESC()
        desc.type = CU_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD
        desc.handle.fd = fd
        desc.flags = 0x00 #0x01  # CUDA_EXTERNAL_SEMAPHORE_HANDLE_FLAG_TIMELINE_SEMAPHORE
        
        # Import external semaphore
        ext_sem = ctypes.c_void_p()
        result = self.cuda.cuImportExternalSemaphore(ctypes.byref(ext_sem), ctypes.byref(desc))
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuImportExternalSemaphore failed: {result}")
        print('succeed')
        return ext_sem
        

    def import_external_memory(self, fd: int, size: int, *, dedicated: bool=True) -> ctypes.c_void_p:
        # 设原型（只设一次；可移到 __init__）
        self.cuda.cuImportExternalMemory.restype  = ctypes.c_int
        self.cuda.cuImportExternalMemory.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(CUDA_EXTERNAL_MEMORY_HANDLE_DESC)
        ]

        desc = CUDA_EXTERNAL_MEMORY_HANDLE_DESC()
        # 清零（ctypes 默认已零，但手动更放心）
        ctypes.memset(ctypes.byref(desc), 0, ctypes.sizeof(desc))

        desc.type = CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD
        desc.fd   = fd
        desc.size = ctypes.c_ulonglong(size)
        desc.flags = CUDA_EXTERNAL_MEMORY_DEDICATED if dedicated else 0

        ext_mem = ctypes.c_void_p()
        result = self.cuda.cuImportExternalMemory(ctypes.byref(ext_mem), ctypes.byref(desc))
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuImportExternalMemory failed: {result} (fd={fd}, size={size}, dedicated={dedicated})")
        return ext_mem


    def signal_semaphore(self, semaphore: ctypes.c_void_p, value: int, stream: Optional[ctypes.c_void_p] = None):
        """Signal external semaphore with timeline value."""
        if stream is None:
            stream = self.stream
        
        # Define CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS structure
        class CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS(ctypes.Structure):
            class Value(ctypes.Union):
                _fields_ = [
                    ("fence", ctypes.c_ulonglong),  # For timeline semaphores
                    ("reserved", ctypes.c_uint),
                ]
            
            _fields_ = [
                ("params", Value),
                ("flags", ctypes.c_uint),
                ("reserved", ctypes.c_uint * 16),
            ]
        
        # Create and populate parameters
        params = CUDA_EXTERNAL_SEMAPHORE_SIGNAL_PARAMS()
        params.params.fence = value
        params.flags = 0
        
        # Signal semaphore
        result = self.cuda.cuSignalExternalSemaphoresAsync(ctypes.byref(semaphore), ctypes.byref(params), 1, stream)
        if result != CUDA_SUCCESS:
            raise RuntimeError(f"cuSignalExternalSemaphoresAsync failed: {result}")
            
    def wait_semaphore(self, semaphore: ctypes.c_void_p, value: int, stream: Optional[ctypes.c_void_p] = None):
        """Wait for external semaphore timeline value."""
        if stream is None:
            stream = self.stream
        
        # Define CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS structure
        class CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS(ctypes.Structure):
            class Value(ctypes.Union):
                _fields_ = [
                    ("fence", ctypes.c_ulonglong),  # For timeline semaphores
                    ("reserved", ctypes.c_uint),
                ]
            
            _fields_ = [
                ("params", Value),
                ("flags", ctypes.c_uint),
                ("reserved", ctypes.c_uint * 16),
            ]
        
        # Create and populate parameters
        params = CUDA_EXTERNAL_SEMAPHORE_WAIT_PARAMS()
        params.params.fence = value
        params.flags = 0
        
        # Wait on semaphore
        result = self.cuda.cuWaitExternalSemaphoresAsync(ctypes.byref(semaphore), ctypes.byref(params), 1, stream)
        if result != CUDA_SUCCESS:
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
                    print('sem_import ok')
                    self.ext_mem_cam = self.cuda_api.import_external_memory(cam_fd, self.cam_bytes)
                    self.ext_mem_color = self.cuda_api.import_external_memory(color_fd, self.color_readback_bytes)
                    
                    
                    

                    # Now import external memory


                    self.dev_cam = self.cuda_api.get_mapped_buffer(self.ext_mem_cam, self.cam_bytes)
                    self.dev_color = self.cuda_api.get_mapped_buffer(self.ext_mem_color, self.color_readback_bytes)
                    

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
            
            # Close file descriptors (CUDA has taken ownership)
            for fd in fds:
                os.close(fd)
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to receive FDs: {e}" + str(type(e)))
            return False
            
    def update_camera(self, view_matrix: np.ndarray, proj_matrix: np.ndarray) -> bool:
        """Update camera parameters."""
        if not self.connected or not self.cuda_api:
            return False
            
        try:
            # Create camera structure
            frame_constants = FrameConstants()
            
            # Set viewport
            frame_constants.viewport[0] = self.width
            frame_constants.viewport[1] = self.height
            frame_constants.viewportf[0] = float(self.width)
            frame_constants.viewportf[1] = float(self.height)
            
            # Set view matrix (column-major)
            for i in range(16):
                frame_constants.viewMatrix[i] = view_matrix.flatten()[i]
                frame_constants.projMatrix[i] = proj_matrix.flatten()[i]
                
            # Compute view-projection matrix
            view_proj = proj_matrix @ view_matrix
            for i in range(16):
                frame_constants.viewProjMatrix[i] = view_proj.flatten()[i]
            
            # Copy to device
            self.cuda_api.memcpy_host_to_device(
                self.dev_cam, 
                ctypes.byref(frame_constants), 
                ctypes.sizeof(frame_constants)
            )
            
            # Signal camera ready
            self.cuda_api.signal_semaphore(self.sem_cam, self.frame_number)
            
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
            start_time = time.time()
            self.cuda_api.wait_semaphore(self.sem_done, self.frame_number)
            self.cuda_api.synchronize_stream()
            
            wait_time = (time.time() - start_time) * 1000
            if wait_time > timeout_ms:
                logger.warning(f"Frame wait took {wait_time:.1f}ms (timeout: {timeout_ms}ms)")
                
            # Create CuPy array from device memory (zero-copy)
            umem = cp.cuda.UnownedMemory(
                int(self.dev_color.value), 
                self.color_readback_bytes, 
                owner=None
            )
            mptr = cp.cuda.MemoryPointer(umem, 0)
            
            # Create properly strided array for row-pitch alignment
            cupy_array = cp.ndarray(
                (self.height, self.width, 4),
                dtype=cp.uint8,
                memptr=mptr,
                strides=(self.row_pitch, 4, 1)
            )
            
            # Convert to PyTorch tensor via DLPack (zero-copy)
            torch_tensor = torch.utils.dlpack.from_dlpack(cupy_array.toDlpack())
            
            # Increment frame counter for next frame
            self.frame_number += 1
            
            return torch_tensor
            
        except Exception as e:
            logger.error(f"Failed to get frame: {e}")
            return None
            
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
            
    def disconnect(self):
        """Disconnect from Vulkan application."""
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

# Example usage and test functions
def create_camera_matrices(distance: float = 5.0, yaw: float = 0.0, pitch: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Create view and projection matrices for camera control."""
    # Simple orbit camera
    import math
    
    # View matrix (camera looking at origin)
    eye = np.array([
        distance * math.cos(pitch) * math.cos(yaw),
        distance * math.sin(pitch),
        distance * math.cos(pitch) * math.sin(yaw)
    ])
    target = np.array([0, 0, 0])
    up = np.array([0, 1, 0])
    
    # Create view matrix
    z = eye - target
    z = z / np.linalg.norm(z)
    x = np.cross(up, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    
    view_matrix = np.array([
        [x[0], y[0], z[0], 0],
        [x[1], y[1], z[1], 0],
        [x[2], y[2], z[2], 0],
        [-np.dot(x, eye), -np.dot(y, eye), -np.dot(z, eye), 1]
    ])
    
    # Projection matrix (perspective)
    fov = math.radians(45.0)
    aspect = 1920.0 / 1080.0  # TODO: use actual resolution
    near = 0.1
    far = 100.0
    
    f = 1.0 / math.tan(fov / 2.0)
    proj_matrix = np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), (2 * far * near) / (near - far)],
        [0, 0, -1, 0]
    ])
    
    return view_matrix, proj_matrix

def main():
    """Main test function."""
    logger.info("Starting VK2Torch client test")
    
    if not HAS_CUPY or not HAS_TORCH:
        logger.error("CuPy and PyTorch are required for this client")
        return
        
    with VK2TorchClient() as client:
        if not client.connect():
            logger.error("Failed to connect to Vulkan application")
            return
            
        logger.info("Connected successfully, starting frame capture loop")
        
        # Test camera movement
        for frame_idx in range(10):
            # Create different camera positions
            yaw = frame_idx * 0.1
            distance = 5.0 + frame_idx * 0.2
            view_matrix, proj_matrix = create_camera_matrices(distance, yaw, 0.0)
            
            # Update camera
            if not client.update_camera(view_matrix, proj_matrix):
                logger.error("Failed to update camera")
                break
                
            # Get frame
            tensor = client.get_frame()
            if tensor is None:
                logger.error("Failed to get frame")
                break
                
            logger.info(f"Frame {frame_idx}: {tensor.shape} {tensor.dtype} on {tensor.device}")
            
            # Save every few frames
            if frame_idx % 3 == 0:
                filename = f"frame_{frame_idx:03d}.png"
                if client.save_frame_png(tensor, filename):
                    logger.info(f"Saved {filename}")
                    
            time.sleep(0.1)  # Small delay
            
        logger.info("Test completed")

if __name__ == "__main__":
    main()