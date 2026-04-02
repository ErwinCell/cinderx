file(GLOB RUNTIME_TEST_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/*.cpp)
file(GLOB RUNTIME_TEST_HIR_INPUTS CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/hir_tests/*.txt)

set(RUNTIME_TESTS_BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR})
set(RUNTIME_TESTS_WORKING_DIR ${RUNTIME_TESTS_BINARY_DIR}/runtime_test_root)
set(RUNTIME_TESTS_HIR_DIR ${RUNTIME_TESTS_WORKING_DIR}/RuntimeTests/hir_tests)
file(MAKE_DIRECTORY ${RUNTIME_TESTS_HIR_DIR})

foreach(HIR_TEST_FILE IN LISTS RUNTIME_TEST_HIR_INPUTS)
  get_filename_component(HIR_TEST_NAME ${HIR_TEST_FILE} NAME)
  file(READ ${HIR_TEST_FILE} HIR_TEST_CONTENTS)
  string(REPLACE "\r\n" "\n" HIR_TEST_CONTENTS "${HIR_TEST_CONTENTS}")
  file(WRITE ${RUNTIME_TESTS_HIR_DIR}/${HIR_TEST_NAME} "${HIR_TEST_CONTENTS}")
endforeach()

add_executable(RuntimeTests ${RUNTIME_TEST_SOURCES})

target_link_libraries(
  RuntimeTests
  PRIVATE
  Python::Python
  Threads::Threads
  GTest::gtest
  asmjit::asmjit
  fmt::fmt
  borrowed
  cached-properties
  common
  immortalize
  interpreter
  jit
  parallel-gc
  static-python
  cinderx-runtime-support)

target_compile_definitions(
  RuntimeTests
  PRIVATE
  BAKED_IN_PYTHONPATH="${CINDERX_SOURCE_DIR}/PythonLib")

enable_testing()
add_test(
  NAME RuntimeTests
  COMMAND RuntimeTests --gtest_color=yes
  WORKING_DIRECTORY ${RUNTIME_TESTS_WORKING_DIR})
