cmake_minimum_required(VERSION 3.10)
project(LearningOverlay)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Threads REQUIRED)

add_executable(overlay
    src/main.cpp
)

target_include_directories(overlay PRIVATE include)

target_link_libraries(overlay
    user32
    gdi32
    ws2_32
    ${CMAKE_THREAD_LIBS_INIT}
)
