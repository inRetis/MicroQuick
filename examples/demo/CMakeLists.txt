mq_add_qml_app(demo_ui
    MAIN Main.qml
    QML_FILES Button.qml Switch.qml ProgressBar.qml
    ASSETS images/logo.png
)

if(MQ_BUILD_SIMULATOR)
    mq_add_simulator(demo demo_ui)
endif()
