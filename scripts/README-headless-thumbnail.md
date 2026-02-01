# Headless Thumbnail Renderer

A Python script for generating 3D model thumbnails in headless environments (no GPU required). This script replicates the lighting and visual style of BambuStudio's thumbnail rendering.

## Features

- **Headless rendering**: Works without display server (X11/Wayland) or GPU
- **BambuStudio-style lighting**: Uses the same dual-light setup and shader parameters
- **Multiple formats**: Supports STL, 3MF, and STEP files
- **Multiple views**: Isometric, front, rear, left, right, top, bottom views
- **Customizable**: Adjust colors, backgrounds, and resolution
- **Batch mode**: Render all views at once

## Installation

### 1. Install system dependencies (for OSMesa software rendering)

**Ubuntu/Debian:**
```bash
sudo apt-get install libosmesa6-dev mesa-utils python3-pip
```

**Fedora/RHEL:**
```bash
sudo dnf install mesa-libOSMesa-devel python3-pip
```

**Arch Linux:**
```bash
sudo pacman -S mesa python-pip
```

### 2. Install Python dependencies

```bash
pip install -r scripts/requirements-thumbnail.txt
```

### 3. (Optional) Install STEP file support

For STEP file support, install one of:

```bash
# Option 1: cadquery (recommended, easier)
pip install cadquery

# Option 2: OCP (more lightweight)
pip install OCP
```

## Usage

### Basic usage

```bash
# Render an STL file
python scripts/headless_thumbnail.py model.stl -o thumbnail.png

# Render a 3MF file
python scripts/headless_thumbnail.py model.3mf -o thumbnail.png

# Render a STEP file (requires cadquery or OCP)
python scripts/headless_thumbnail.py model.step -o thumbnail.png
```

### Options

```
-o, --output PATH      Output PNG file (required)
-s, --size SIZE        Output size in pixels (default: 512)
-W, --width WIDTH      Output width (overrides --size)
-H, --height HEIGHT    Output height (overrides --size)
-v, --view VIEW        Camera view angle (default: iso)
-c, --color R G B A    Model color as RGBA (0.0-1.0 range)
-b, --background R G B A  Background color as RGBA (0-255 range)
--no-transparent       Disable transparent background
--software-only        Use software rendering only (slower but always works)
--batch                Render all standard views
```

### View angles

| View | Description |
|------|-------------|
| `iso` | Isometric view (default) |
| `iso_1` | Isometric rotated 90 degrees clockwise |
| `iso_2` | Isometric rotated 180 degrees |
| `iso_3` | Isometric rotated 270 degrees clockwise |
| `front` | Front view |
| `rear` | Rear view |
| `left` | Left side view |
| `right` | Right side view |
| `top` | Top view |
| `bottom` | Bottom view |
| `top_front` | Top-front angled view (used in 3MF thumbnails) |

### Examples

```bash
# Custom size
python scripts/headless_thumbnail.py model.stl -o thumb.png --size 256

# Specific view
python scripts/headless_thumbnail.py model.stl -o front.png --view front

# Custom color (blue)
python scripts/headless_thumbnail.py model.stl -o blue.png --color 0.2 0.5 0.9 1.0

# White background
python scripts/headless_thumbnail.py model.stl -o thumb.png --background 255 255 255 255

# Render all views
python scripts/headless_thumbnail.py model.stl -o views.png --batch
# Creates: views_iso.png, views_front.png, views_rear.png, etc.
```

## Lighting Model

This script uses the same lighting parameters as BambuStudio's thumbnail shader:

| Parameter | Value |
|-----------|-------|
| Intensity correction | 0.6 |
| **Top Light** | |
| Direction | (-0.457, 0.457, 0.762) |
| Diffuse | 0.48 |
| Specular | 0.075 |
| Shininess | 20.0 |
| **Front Light** | |
| Direction | (0.699, 0.140, 0.699) |
| Diffuse | 0.18 |
| **Ambient** | 0.3 |
| **Emission** | 0.1 |

## Troubleshooting

### "Cannot open display" or "No display" errors

Make sure the environment variables are set:
```bash
export PYOPENGL_PLATFORM=osmesa
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_GL_VERSION_OVERRIDE=3.3
```

### OSMesa not found

Install the OSMesa development package for your distribution (see Installation above).

### STEP files not loading

Install cadquery or OCP for STEP support:
```bash
pip install cadquery
```

### Low quality output

The script tries to use pyrender for best quality. If it falls back to software rendering, install pyrender and PyOpenGL:
```bash
pip install pyrender PyOpenGL
```

## Architecture

The script uses:
- **trimesh**: For loading 3D model files (STL, 3MF, STEP)
- **pyrender**: For high-quality OpenGL rendering with OSMesa backend
- **numpy**: For matrix/vector operations and lighting calculations
- **Pillow**: For image output

When pyrender is not available, it falls back to trimesh's built-in software renderer.

## License

This script is part of BambuStudio and follows the same license terms.
