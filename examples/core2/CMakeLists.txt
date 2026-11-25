# Same UI as the M5Stack Core2 firmware (ports/m5stack-core2), runnable in the
# desktop simulator at 320x240.
mq_add_qml_app(core2_ui
    MAIN Main.qml
    QML_FILES ../demo/Button.qml ../demo/Switch.qml ../demo/ProgressBar.qml
    ASSETS ../demo/images/logo.png
)

if(MQ_BUILD_SIMULATOR)
    mq_add_simulator(core2_demo core2_ui)
endif()
