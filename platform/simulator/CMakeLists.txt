# The simulator provides main(); link it with a library made by mq_add_qml_app.
add_library(mq_simulator STATIC main.cpp)
target_link_libraries(mq_simulator PUBLIC microquick Qt6::Core Qt6::Gui)
# Qt headers need exceptions/RTTI-agnostic flags only on this host target.
target_compile_options(mq_simulator PRIVATE -frtti -fexceptions)

function(mq_add_simulator target app_lib)
    add_executable(${target} $<TARGET_OBJECTS:mq_simulator>)
    target_link_libraries(${target} PRIVATE ${app_lib} microquick Qt6::Core Qt6::Gui)
endfunction()
