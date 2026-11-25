add_library(microquick STATIC
    src/animation.cpp
    src/global.cpp
    src/items.cpp
    src/painter.cpp
    src/property.cpp
    src/string.cpp
    src/views.cpp
    src/window.cpp
)
target_include_directories(microquick PUBLIC include)
# MCU friendly: no exceptions, no RTTI, no dynamic allocation in the runtime.
target_compile_options(microquick PUBLIC
    $<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions -fno-rtti>
    -Wall -Wextra)
if(MQ_HOST_BUILD)
    target_compile_definitions(microquick PUBLIC MQ_HOSTED=1)
endif()
