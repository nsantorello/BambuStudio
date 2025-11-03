# Bambu Studio Headless Server Usage Guide

## Overview

Bambu Studio supports headless (no display/GPU) operation for slicing 3MF files on Linux servers. This guide explains how to build and use Bambu Studio with thumbnail generation on servers without a display.

## How It Works

Bambu Studio uses **OSMesa (Off-Screen Mesa)** for software-based OpenGL rendering without requiring:
- X11 or Wayland display server
- Physical GPU
- Display connection

The thumbnail generation system (located in `src/BambuStudio.cpp:5754-6563`) automatically:
1. Initializes an invisible GLFW window using OSMesa
2. Renders thumbnails using software OpenGL
3. Embeds thumbnails into G-code and 3MF files
4. Falls back gracefully if OpenGL initialization fails (slicing continues without thumbnails)

## System Requirements

### Required Packages (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install -y \
    libosmesa6-dev \
    mesa-common-dev \
    libgl1-mesa-dev \
    libglu1-mesa-dev
```

### Required Packages (RHEL/CentOS/Fedora)
```bash
sudo dnf install -y \
    mesa-libOSMesa-devel \
    mesa-libGL-devel \
    mesa-libGLU-devel
```

## Building Bambu Studio for Headless Use

### 1. Clean Previous Builds (if applicable)
```bash
# Remove old GLFW build to force rebuild with OSMesa
rm -rf deps/build/dep_GLFW-prefix/
```

### 2. Build Dependencies with OSMesa Support

The GLFW dependency is now configured to build with OSMesa support on Linux (see `deps/GLFW/GLFW.cmake:11`).

```bash
# Build dependencies
cd deps
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
cd ../..
```

### 3. Build Bambu Studio

```bash
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
         -DCMAKE_PREFIX_PATH=$(pwd)/../deps/build/destdir/usr/local \
         -DSLIC3R_STATIC=1
make -j$(nproc)
```

## Usage

### Basic Slicing with Thumbnails

```bash
./bambu-studio-console \
    --slice \
    --load /path/to/config.ini \
    --output /path/to/output.gcode \
    /path/to/model.3mf
```

### Common CLI Options

- `--slice` - Perform slicing operation
- `--load <file>` - Load configuration from file
- `--output <file>` - Specify output G-code file
- `--export-3mf <file>` - Export as 3MF file with thumbnails
- `--help` - Show all available options

### Example: Slice with Custom Settings

```bash
./bambu-studio-console \
    --slice \
    --load printer-settings.ini \
    --layer-height 0.2 \
    --infill-density 20 \
    --output output.gcode \
    model.3mf
```

## Thumbnail Configuration

Thumbnails are automatically generated when:
1. OSMesa libraries are installed
2. GLFW is built with OSMesa support
3. OpenGL initialization succeeds

### Thumbnail Sizes

Default thumbnail sizes are defined in the printer profile. Common sizes:
- Small: 32x32 (for quick preview)
- Medium: 400x300 (for printer LCD)
- Large: 800x600 (for detailed preview)

### Verifying Thumbnail Generation

Check the log output for:

**Success:**
```
[info] init opengl succeeded
[info] Generating thumbnails for plate 1
```

**Failure (missing OSMesa):**
```
[error] init opengl failed! skip thumbnail generating
[error] Failed to create GLFW window
```

If thumbnails fail, slicing will continue but the G-code/3MF will not contain embedded preview images.

## Troubleshooting

### Error: "Failed to create GLFW window"

**Cause:** OSMesa libraries not installed or GLFW not built with OSMesa support.

**Solution:**
1. Install OSMesa development packages (see System Requirements)
2. Clean and rebuild GLFW: `rm -rf deps/build/dep_GLFW-prefix/`
3. Rebuild dependencies and Bambu Studio

### Error: Wayland/X11 Related Errors

**Cause:** Code is trying to use display server instead of OSMesa.

**Solution:** Set environment variable to disable display:
```bash
export DISPLAY=
./bambu-studio-console --slice ...
```

### Performance Considerations

**Software rendering is slower than GPU rendering:**
- Simple models: 1-5 seconds per thumbnail
- Complex models: 5-30 seconds per thumbnail

For production servers:
- Use sufficient CPU cores
- Consider thumbnail generation overhead in processing time estimates
- Thumbnails can be disabled if not needed (slicing continues without them)

## Code Architecture

### Key Files

| File | Purpose |
|------|---------|
| `src/BambuStudio.cpp:5792` | OSMesa initialization for Linux |
| `src/BambuStudio.cpp:6546` | CLI thumbnail generation callback |
| `src/slic3r/GUI/GLCanvas3D.cpp:6623` | Framebuffer-based rendering |
| `deps/GLFW/GLFW.cmake:11` | GLFW build configuration with OSMesa |

### Rendering Pipeline

1. **Initialization** (`init_opengl_and_colors` lambda):
   - Create invisible GLFW window with OSMesa context
   - Initialize OpenGL via GLEW
   - Load shaders and model data

2. **Thumbnail Generation** (`cli_generate_thumbnails` lambda):
   - For each thumbnail size
   - Render to framebuffer using `GLCanvas3D::render_thumbnail_framebuffer()`
   - Read pixels back to CPU memory
   - Encode as PNG

3. **G-code Export**:
   - Call `Print::export_gcode()` with thumbnail callback
   - Embed thumbnail data in G-code comments or 3MF metadata

## Docker Usage

Example Dockerfile for headless slicing:

```dockerfile
FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential cmake git \
    libosmesa6-dev mesa-common-dev \
    libgl1-mesa-dev libglu1-mesa-dev \
    libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and build Bambu Studio
COPY . /app/bambustudio
WORKDIR /app/bambustudio

# Build dependencies
RUN cd deps && mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc)

# Build Bambu Studio
RUN mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release \
             -DCMAKE_PREFIX_PATH=/app/bambustudio/deps/build/destdir/usr/local \
             -DSLIC3R_STATIC=1 && \
    make -j$(nproc)

WORKDIR /app/bambustudio/build
ENTRYPOINT ["./bambu-studio-console"]
```

## Additional Notes

- The headless mode is fully automatic - no configuration changes needed
- Thumbnails are optional - slicing works even if thumbnail generation fails
- Software rendering quality is identical to GPU rendering
- OSMesa uses CPU for rendering, so thumbnail generation time scales with CPU performance

## Support

For issues related to headless operation:
1. Check logs for OpenGL initialization messages
2. Verify OSMesa packages are installed: `ldconfig -p | grep OSMesa`
3. Test GLFW OSMesa support: `ldd build/bambu-studio-console | grep osmesa`

For questions or bug reports, visit: https://github.com/bambulab/BambuStudio/issues
