cmake_minimum_required (VERSION 2.8.11)
project (test)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(test test_completion.cpp test_fixits)
