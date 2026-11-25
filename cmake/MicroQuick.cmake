# mq_add_qml_app(<target> MAIN <Main.qml> [QML_FILES <files>...] [ASSETS <files>...] [FONT <ttf>])
#
# Compiles QML files to C++ with mqc and converts fonts/images with mqassets,
# producing a static library <target> exposing `mq::Item *mq_app_root()`.
#
# When cross-compiling, set MQ_ASSETS_EXECUTABLE to a host build of mqassets.

set(MQ_ROOT_DIR "${CMAKE_CURRENT_LIST_DIR}/.." CACHE INTERNAL "")
set(MQ_DEFAULT_FONT "${MQ_ROOT_DIR}/fonts/DejaVuSans.ttf" CACHE FILEPATH "Default font rasterized by mqassets")

function(mq_add_qml_app target)
    cmake_parse_arguments(ARG "" "MAIN;FONT" "QML_FILES;ASSETS" ${ARGN})
    if(NOT ARG_MAIN)
        message(FATAL_ERROR "mq_add_qml_app: MAIN is required")
    endif()
    if(NOT ARG_FONT)
        set(ARG_FONT "${MQ_DEFAULT_FONT}")
    endif()
    set(out "${CMAKE_CURRENT_BINARY_DIR}/${target}_generated")
    set(mqc "${MQ_ROOT_DIR}/tools/mqc/mqc.py")
    file(GLOB mqc_sources "${MQ_ROOT_DIR}/tools/mqc/*.py")

    set(qml_abs)
    foreach(f ${ARG_MAIN} ${ARG_QML_FILES})
        get_filename_component(a "${f}" ABSOLUTE)
        list(APPEND qml_abs "${a}")
    endforeach()
    set(asset_abs)
    set(asset_args)
    foreach(f ${ARG_ASSETS})
        get_filename_component(a "${f}" ABSOLUTE)
        list(APPEND asset_abs "${a}")
        list(APPEND asset_args --asset "${a}")
    endforeach()
    list(GET qml_abs 0 main_abs)
    list(REMOVE_AT qml_abs 0)

    add_custom_command(
        OUTPUT "${out}/mq_app.h" "${out}/mq_app.cpp" "${out}/mq_assets.txt"
        COMMAND "${Python3_EXECUTABLE}" "${mqc}" --main "${main_abs}" --out "${out}" ${asset_args} ${qml_abs}
        DEPENDS "${main_abs}" ${qml_abs} ${asset_abs} ${mqc_sources}
        COMMENT "mqc: compiling QML for ${target}"
        VERBATIM)

    if(MQ_ASSETS_EXECUTABLE)
        set(mqassets "${MQ_ASSETS_EXECUTABLE}")
        set(mqassets_dep)
    else()
        set(mqassets $<TARGET_FILE:mqassets>)
        set(mqassets_dep mqassets)
    endif()
    add_custom_command(
        OUTPUT "${out}/mq_assets.cpp"
        COMMAND ${mqassets} --manifest "${out}/mq_assets.txt" --font "${ARG_FONT}" --out "${out}/mq_assets.cpp"
        DEPENDS "${out}/mq_assets.txt" "${ARG_FONT}" ${asset_abs} ${mqassets_dep}
        COMMENT "mqassets: rasterizing fonts / converting images for ${target}"
        VERBATIM)

    add_library(${target} STATIC "${out}/mq_app.cpp" "${out}/mq_assets.cpp")
    target_include_directories(${target} PUBLIC "${out}")
    target_link_libraries(${target} PUBLIC microquick)
endfunction()
