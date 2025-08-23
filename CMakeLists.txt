cmake_minimum_required(VERSION 3.22 FATAL_ERROR)
get_filename_component(PROJECT_NAME ${CMAKE_CURRENT_SOURCE_DIR} NAME)
project(${PROJECT_NAME} LANGUAGES C CXX)

option(NVPRO2_ENABLE_nvgl OFF)
option(NVPRO2_ENABLE_nvgpu_monitor OFF)
option(NVPRO2_ENABLE_nvslang OFF)
option(NVPRO2_ENABLE_nvvkgltf OFF)


# Add the cmake folder to the module path
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
find_package(NvproCore2 REQUIRED)
find_package(Threads REQUIRED)

set_property(GLOBAL PROPERTY USE_FOLDERS ON)
set(CMAKE_CXX_STANDARD 20)

# RPATH settings to avoid conda library conflicts
set(CMAKE_SKIP_RPATH OFF)
set(CMAKE_BUILD_WITH_INSTALL_RPATH OFF)
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH ON)
set(CMAKE_INSTALL_RPATH "/usr/lib/x86_64-linux-gnu")
set(CMAKE_BUILD_RPATH "/usr/lib/x86_64-linux-gnu")

#####################################################################################
# Download the default scene
download_files(FILENAMES bunny_v2.zip EXTRACT)

#####################################################################################
# extra libraries

if(NOT TARGET nv_cluster_lod_builder)
  add_subdirectory(external/nv_cluster_lod_builder)
endif()

#####################################################################################
# Source files for this project
#
file(GLOB SOURCE_FILES src/*.*)
list(FILTER SOURCE_FILES EXCLUDE REGEX "dlss*")

# Add VMA implementation file
list(APPEND SOURCE_FILES src/thirdparty/vma_impl.cpp)

# Add core files
file(GLOB CORE_FILES src/core/*.*)

# Add pybridge files
file(GLOB PYBRIDGE_FILES src/pybridge/*.*)

file(GLOB SHADER_FILES shaders/*.glsl shaders/*.h)
file(GLOB VK_RADIX_SORT_FILES thirdparty/vulkan_radix_sort/src/vk_radix_sort.cc)

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/thirdparty)
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/thirdparty/vulkan_radix_sort/include)

#####################################################################################
# Executable
#

add_executable(${PROJECT_NAME} ${SOURCE_FILES} ${CORE_FILES} ${PYBRIDGE_FILES} ${SHADER_FILES} ${VK_RADIX_SORT_FILES})
set_property(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR} PROPERTY VS_STARTUP_PROJECT ${PROJECT_NAME})

target_link_libraries(${PROJECT_NAME} PRIVATE
  nvpro2::nvapp
  nvpro2::nvgui
  nvpro2::nvutils
  nvpro2::nvvk
  nvpro2::nvvkglsl
  nv_cluster_lod_builder
  meshoptimizer
  cgltf
  Threads::Threads
)

# Force static linking of standard libraries to reduce conda conflicts
target_link_options(${PROJECT_NAME} PRIVATE -static-libstdc++ -static-libgcc)

#####################################################################################
# Adding DLSS if selected
option(USE_DLSS "Use DLSS-RR for denoising" ON)
if(USE_DLSS)
  message(STATUS "Using DLSS-RR for denoising")
    download_package(
      NAME DLSSRR
      URLS https://github.com/NVIDIA/DLSS/archive/refs/tags/v310.3.0.zip
      VERSION 310.3.0
      LOCATION DLSSRR_SOURCE_DIR
    )

    # Set NGX SDK root path
    set(NGX_SDK_ROOT "${DLSSRR_SOURCE_DIR}/DLSS-310.3.0/")
    message(STATUS " - DLSS path: " ${NGX_SDK_ROOT})
    include(cmake/ngx.cmake)
    
    target_link_libraries(${PROJECT_NAME} PRIVATE ngx)
    target_compile_definitions(${PROJECT_NAME} PRIVATE USE_DLSS)
    list(APPEND SOURCE_FILES 
        ${CMAKE_CURRENT_SOURCE_DIR}/src/dlss_wrapper.cpp 
        ${CMAKE_CURRENT_SOURCE_DIR}/src/dlss_wrapper.hpp
        ${CMAKE_CURRENT_SOURCE_DIR}/src/dlss_denoiser.cpp 
        ${CMAKE_CURRENT_SOURCE_DIR}/src/dlss_denoiser.hpp
        )
    target_sources(${PROJECT_NAME} PRIVATE ${SOURCE_FILES})
    source_group("Source Files" FILES ${SOURCE_FILES})

    if (WIN32)
        if(CMAKE_BUILD_TYPE STREQUAL "Debug")
            file(GLOB DLSS_DLLS "${NGX_SDK_ROOT}/lib/Windows_x86_64/dev/nvngx_*.dll")
        else()
            file(GLOB DLSS_DLLS "${NGX_SDK_ROOT}/lib/Windows_x86_64/rel/nvngx_*.dll")
        endif()
    else()
        if(CMAKE_BUILD_TYPE STREQUAL "Debug")
            file(GLOB DLSS_DLLS "${NGX_SDK_ROOT}/lib/Linux_x86_64/dev/libnvidia-ngx*.so.*")
        else()
            file(GLOB DLSS_DLLS "${NGX_SDK_ROOT}/lib/Linux_x86_64/rel/libnvidia-ngx*.so.*")
        endif()    
    endif()

    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${DLSS_DLLS} $<TARGET_FILE_DIR:${PROJECT_NAME}> VERBATIM
        )

    install(FILES ${DLSS_DLLS} DESTINATION ${CMAKE_INSTALL_PREFIX})

endif()

#####################################################################################
# source groups

source_group("Shader Files" FILES ${SHADER_FILES})
source_group("Source Files" FILES ${SOURCE_FILES})


#####################################################################################
# finalize project
#
add_project_definitions(${PROJECT_NAME})
copy_to_runtime_and_install( ${PROJECT_NAME}
    NVSHADERS_FILES "${NVSHADERS_DIR}/nvshaders/slang_types.h"
                    "${NVSHADERS_DIR}/nvshaders/sky_io.h.slang"
                    "${NVSHADERS_DIR}/nvshaders/sky_functions.h.slang"
                    "${NVSHADERS_DIR}/nvshaders/constants.h.slang"
    LOCAL_DIRS "${CMAKE_CURRENT_LIST_DIR}/shaders"
    AUTO
)

#####################################################################################
# Python Extension (vk2torch_ext) - optional
#
option(BUILD_PYTHON_EXT "Build Python extension vk2torch_ext" ON)

if(BUILD_PYTHON_EXT)
  # Find Python and pybind11
  find_package(Python3 COMPONENTS Interpreter Development)
  
  if(Python3_FOUND)
    # Try to find pybind11
    find_package(pybind11 QUIET CONFIG)
    
    if(NOT pybind11_FOUND)
      # Try to find pybind11 via Python
      execute_process(
        COMMAND ${Python3_EXECUTABLE} -c "import pybind11; print(pybind11.get_include())"
        OUTPUT_VARIABLE PYBIND11_INCLUDE_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE PYBIND11_RESULT
      )
      
      if(PYBIND11_RESULT EQUAL 0)
        message(STATUS "Found pybind11 via Python at: ${PYBIND11_INCLUDE_DIR}")
        
        # Manually setup pybind11
        include_directories(${PYBIND11_INCLUDE_DIR})
        
        # Create Python extension module
        add_library(vk2torch_ext MODULE src/pybind/vk2torch_ext.cpp)
        
        # Link minimal required libraries (avoid PIC issues)
        target_link_libraries(vk2torch_ext PRIVATE
          ${Python3_LIBRARIES}
          Threads::Threads
        )
        
        # Set module properties
        set_target_properties(vk2torch_ext PROPERTIES
          PREFIX ""
          OUTPUT_NAME "vk2torch_ext"
          CXX_VISIBILITY_PRESET hidden
          VISIBILITY_INLINES_HIDDEN ON
        )
        
        # Add compile definitions
        target_compile_definitions(vk2torch_ext PRIVATE VERSION_INFO="dev")
        target_compile_definitions(vk2torch_ext PRIVATE PYBIND11_MODULE)
        
        message(STATUS "vk2torch_ext Python extension will be built")
        
      else()
        message(WARNING "pybind11 not found - skipping Python extension")
      endif()
    else()
      message(STATUS "Found pybind11 CONFIG")
      
      # Create Python extension module using pybind11 facilities
      pybind11_add_module(vk2torch_ext src/pybind/vk2torch_ext.cpp)
      
      # Link minimal required libraries (avoid PIC issues)
      target_link_libraries(vk2torch_ext PRIVATE
        ${Python3_LIBRARIES}
        Threads::Threads
      )
      
      # Set module properties
      set_target_properties(vk2torch_ext PROPERTIES
        OUTPUT_NAME "vk2torch_ext"
      )
      
      message(STATUS "vk2torch_ext Python extension will be built (using pybind11 CONFIG)")
    endif()
  else()
    message(WARNING "Python3 not found - skipping Python extension")
  endif()
else()
  message(STATUS "Python extension build disabled")
endif()

