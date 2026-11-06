cmake_minimum_required(VERSION 3.24)
project(EggieQtCocoaRepair LANGUAGES C CXX OBJC OBJCXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 6.10.3 EXACT REQUIRED COMPONENTS Core Gui CorePrivate GuiPrivate)
if(NOT EGGIE_QTBASE_SOURCE)
  message(FATAL_ERROR "EGGIE_QTBASE_SOURCE must name the patched Qt 6.10.3 source directory")
endif()
set(COCOA "${EGGIE_QTBASE_SOURCE}/src/plugins/platforms/cocoa")
file(GLOB cocoa_sources "${COCOA}/*.mm" "${COCOA}/*.cpp" "${COCOA}/*.h")
# These source fragments are included by qnsview.mm.
list(FILTER cocoa_sources EXCLUDE REGEX "/qnsview_[^/]+\\.mm$")
if(NOT QT_FEATURE_opengl)
  list(FILTER cocoa_sources EXCLUDE REGEX "/qcocoaglcontext\\.(mm|h)$")
endif()
if(NOT QT_FEATURE_vulkan)
  list(FILTER cocoa_sources EXCLUDE REGEX "/qcocoavulkaninstance\\.(mm|h)$")
endif()
if(NOT QT_FEATURE_sessionmanager)
  list(FILTER cocoa_sources EXCLUDE REGEX "/qcocoasessionmanager\\.(cpp|h)$")
endif()
add_library(qcocoa MODULE ${cocoa_sources})
set_target_properties(qcocoa PROPERTIES
  SUFFIX ".dylib"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/platforms"
  OSX_ARCHITECTURES arm64
)
target_include_directories(qcocoa PRIVATE "${COCOA}")
target_compile_definitions(qcocoa PRIVATE QT_PLUGIN QT_NO_FOREACH QT_NO_DEBUG)
target_link_libraries(qcocoa PRIVATE Qt6::CorePrivate Qt6::GuiPrivate)
foreach(fw Foundation AppKit Carbon CoreServices CoreVideo IOKit IOSurface Metal QuartzCore UniformTypeIdentifiers)
  find_library(${fw}_LIB ${fw} REQUIRED)
  target_link_libraries(qcocoa PRIVATE "${${fw}_LIB}")
endforeach()
qt_add_resources(qcocoa "qcocoaresources"
  PREFIX "/qt-project.org/mac/cursors"
  BASE "${COCOA}"
  FILES "${COCOA}/images/sizeallcursor.png" "${COCOA}/images/spincursor.png" "${COCOA}/images/waitcursor.png"
)
