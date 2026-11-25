add_executable(test_runtime test_runtime.cpp)
target_link_libraries(test_runtime PRIVATE microquick)
add_test(NAME runtime COMMAND test_runtime)

if(MQ_BUILD_EXAMPLES)
    add_executable(test_demo test_demo.cpp)
    target_link_libraries(test_demo PRIVATE demo_ui)
    add_test(NAME demo COMMAND test_demo)
endif()

add_test(NAME mqc COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s "${CMAKE_CURRENT_SOURCE_DIR}" -p "test_mqc.py" -v)
