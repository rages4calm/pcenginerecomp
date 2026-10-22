cmake_minimum_required(VERSION 3.20)
project(pcenginerecomp VERSION 0.1.0 LANGUAGES CXX)

add_library(pce-runtime STATIC runtime/src/runtime.cpp)
target_include_directories(pce-runtime PUBLIC runtime/include)
target_compile_features(pce-runtime PUBLIC cxx_std_20)
set_target_properties(pce-runtime PROPERTIES CXX_EXTENSIONS OFF)
if(MSVC)
  target_compile_options(pce-runtime PRIVATE /W4)
else()
  target_compile_options(pce-runtime PRIVATE -Wall -Wextra -Wpedantic)
endif()

set(PCE_MODULE_SOURCE "" CACHE FILEPATH "Locally generated module.cpp; empty builds interpreter-only sandbox")
if(PCE_MODULE_SOURCE)
  if(NOT EXISTS "${PCE_MODULE_SOURCE}")
    message(FATAL_ERROR "PCE_MODULE_SOURCE does not exist")
  endif()
  set(PCE_MODULE "${PCE_MODULE_SOURCE}")
else()
  set(PCE_MODULE runtime/src/no_module.cpp)
endif()
add_executable(pce-headless runtime/src/headless.cpp "${PCE_MODULE}")
target_link_libraries(pce-headless PRIVATE pce-runtime)

include(CTest)
option(PCE_BUILD_REFERENCE_PROBE "Build optional synthetic single-step reference probe" OFF)
if(PCE_BUILD_REFERENCE_PROBE)
  find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
  set(ORACLE_DIR "${CMAKE_CURRENT_BINARY_DIR}/oracle-fixture")
  add_custom_command(OUTPUT "${ORACLE_DIR}/module.cpp" "${ORACLE_DIR}/fixture.hpp"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/generate_fixture.py" "${ORACLE_DIR}" oracle
    DEPENDS tests/generate_fixture.py pcerecomp/analysis.py pcerecomp/isa.py pcerecomp/emitter.py pcerecomp/data_ops.py
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" VERBATIM)
  add_executable(pce-oracle-probe tests/oracle_probe.cpp "${ORACLE_DIR}/module.cpp" "${ORACLE_DIR}/fixture.hpp")
  target_include_directories(pce-oracle-probe PRIVATE "${ORACLE_DIR}")
  target_link_libraries(pce-oracle-probe PRIVATE pce-runtime)
endif()
if(BUILD_TESTING)
  find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
  add_test(NAME frontend COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s tests -p test_*.py -v)
  set_tests_properties(frontend PROPERTIES WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    ENVIRONMENT "PCE_TEST_HEADLESS=$<TARGET_FILE:pce-headless>")

  set(FIXTURE_DIR "${CMAKE_CURRENT_BINARY_DIR}/fixture")
  add_custom_command(OUTPUT "${FIXTURE_DIR}/module.cpp" "${FIXTURE_DIR}/fixture.hpp"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/generate_fixture.py" "${FIXTURE_DIR}"
    DEPENDS tests/generate_fixture.py pcerecomp/analysis.py pcerecomp/isa.py pcerecomp/emitter.py pcerecomp/data_ops.py
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" VERBATIM)
  add_executable(pce-runtime-tests tests/runtime_tests.cpp "${FIXTURE_DIR}/module.cpp" "${FIXTURE_DIR}/fixture.hpp")
  target_include_directories(pce-runtime-tests PRIVATE "${FIXTURE_DIR}")
  target_link_libraries(pce-runtime-tests PRIVATE pce-runtime)
  add_test(NAME runtime COMMAND pce-runtime-tests)
endif()
