# MicroQuick on M5Stack Core2 (PlatformIO)

Runs the QML UI of [`examples/core2`](../../examples/core2/Main.qml) on an
M5Stack Core2: ESP32 at 240 MHz with 8 MB PSRAM, ILI9342C 320x240 SPI display,
FT6336U capacitive touch, AXP192 power management.

## Requirements

- VS Code with the **PlatformIO IDE** extension.
- Qt 6 installed on the computer (for the `mqassets` host tool that rasterizes
  the fonts; it is built automatically from this repository the first time).
- Python 3 and CMake (PlatformIO ships Python; CMake is only needed to build
  `mqassets` if `build/tools/mqassets/mqassets` does not exist yet).

## Build and flash from VS Code

1. **File › Open Folder…** and open `ports/m5stack-core2` (the folder that
   contains `platformio.ini`), not the repository root.
2. Plug in the Core2 over USB-C.
3. In the PlatformIO toolbar (status bar at the bottom), click **✓ Build**, then
   **→ Upload**, then **🔌 Monitor** to see `console.log()` output.

The first build downloads the pioarduino ESP32 platform and M5Unified. Each
build first runs `scripts/mq_generate.py`, which compiles the QML to C++ and
converts the fonts and images into `src/mq_generated/` (only when a QML file,
an asset or the compiler changed).

From a terminal, the same thing:

```bash
cd ports/m5stack-core2
pio run -t upload && pio device monitor
```

## Changing the UI

- Edit `examples/core2/Main.qml` (or point `custom_mq_main` / `custom_mq_qml`
  in `platformio.ini` at your own files). Keep `width: 320; height: 240`.
- Preview it on the computer before flashing:
  `./build/examples/core2/core2_demo --zoom 3` (after `cmake --build build`).
- QML errors are reported by the build with file and line.

## How the port works

`src/main.cpp` is the whole board support:

- `M5.begin()` powers and configures the display and touch (AXP192, M5GFX).
- The 320x240 RGB565 framebuffer is allocated once in PSRAM.
- With `-DMQ_APP_PLATFORM_STORAGE`, the application state (~80 KB) and the
  binding link pool are placed in the internal heap at startup through
  `mq_platform_alloc()`: the ESP32 static RAM segment is too small for them.
  After `setup()`, nothing is allocated any more.
- `loop()` polls the touch panel (presses on the three red circles below the
  screen are ignored), runs `Window::processFrame(millis())` and pushes only the
  repainted rectangles to the display.
- Every 10 s, frame count, binding links and free heap are printed on the
  serial monitor.

Typical figures (from the serial monitor): free internal heap ≈ 200 KB after
startup, 235 binding links used out of 743 reserved, ≈ 866 KB of flash.
