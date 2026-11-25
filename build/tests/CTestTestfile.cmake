# CMake generated Testfile for 
# Source directory: /Users/huston/Programmation/MicroQuick/tests
# Build directory: /Users/huston/Programmation/MicroQuick/build/tests
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test("runtime" "/Users/huston/Programmation/MicroQuick/build/tests/test_runtime")
set_tests_properties("runtime" PROPERTIES  _BACKTRACE_TRIPLES "/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;3;add_test;/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;0;")
add_test("demo" "/Users/huston/Programmation/MicroQuick/build/tests/test_demo")
set_tests_properties("demo" PROPERTIES  _BACKTRACE_TRIPLES "/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;8;add_test;/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;0;")
add_test("mqc" "/opt/homebrew/Frameworks/Python.framework/Versions/3.15/bin/python3.15" "-m" "unittest" "discover" "-s" "/Users/huston/Programmation/MicroQuick/tests" "-p" "test_mqc.py" "-v")
set_tests_properties("mqc" PROPERTIES  _BACKTRACE_TRIPLES "/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;11;add_test;/Users/huston/Programmation/MicroQuick/tests/CMakeLists.txt;0;")
