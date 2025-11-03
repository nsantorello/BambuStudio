# Headless Server - Quick Start Guide

## Which Method Should I Use?

### Using Official Binaries? → Use Xvfb (Runtime Solution)

**✅ Recommended for most users**

```bash
# Install Xvfb
sudo apt-get install xvfb mesa-utils

# Slice with thumbnails
xvfb-run -a ./bambu-studio-console \
    --slice \
    --load config.ini \
    --output output.gcode \
    model.3mf
```

📖 **Full guide:** [doc/Headless Server Usage - Runtime Only.md](doc/Headless%20Server%20Usage%20-%20Runtime%20Only.md)

**Pros:**
- ✅ No rebuild needed
- ✅ Works with any Bambu Studio version
- ✅ Simple to set up
- ✅ Production-ready

**Cons:**
- ⚠️ Requires X11 virtual display (uses more memory)
- ⚠️ Slightly more complex setup for automation

---

### Building from Source? → Use OSMesa (Build Solution)

**For developers and custom builds**

This repository now includes OSMesa support in the build configuration:

```bash
# Install OSMesa
sudo apt-get install libosmesa6-dev mesa-common-dev

# Build with OSMesa support (GLFW will automatically use it)
cd deps/build && cmake .. && make
cd ../../build && cmake .. && make
```

📖 **Full guide:** [doc/Headless Server Usage.md](doc/Headless%20Server%20Usage.md)

**Pros:**
- ✅ No X server needed at all
- ✅ Lower memory usage
- ✅ Cleaner architecture

**Cons:**
- ⚠️ Must rebuild on each Bambu Studio update
- ⚠️ Requires build environment setup
- ⚠️ More complex build process

---

## Quick Comparison

| Feature | Xvfb (Runtime) | OSMesa (Build) |
|---------|----------------|----------------|
| **Official binaries** | ✅ Yes | ❌ No |
| **Setup time** | 5 minutes | 30-60 minutes |
| **Memory usage** | ~100-200 MB | ~50-100 MB |
| **Requires rebuild** | ❌ No | ✅ Yes |
| **Maintenance** | Easy | Medium |

---

## Example: Docker with Xvfb (Easiest)

Perfect for CI/CD and production:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    xvfb mesa-utils wget

# Install official Bambu Studio .deb
RUN wget https://example.com/bambu-studio.deb && \
    apt-get install -y ./bambu-studio.deb

# Wrapper script
RUN echo '#!/bin/bash\nxvfb-run -a bambu-studio-console "$@"' > /usr/local/bin/slice
RUN chmod +x /usr/local/bin/slice

ENTRYPOINT ["/usr/local/bin/slice"]
```

```bash
docker build -t slicer .
docker run --rm -v $(pwd):/work slicer --slice --load cfg.ini --output out.gcode model.3mf
```

---

## Verification

Both methods should embed thumbnails. Check with:

```bash
# G-code files
head -100 output.gcode | grep thumbnail

# 3MF files
unzip -l output.3mf | grep thumbnail
```

---

## Need Help?

- **Xvfb method:** See [doc/Headless Server Usage - Runtime Only.md](doc/Headless%20Server%20Usage%20-%20Runtime%20Only.md)
- **OSMesa method:** See [doc/Headless Server Usage.md](doc/Headless%20Server%20Usage.md)
- **Report issues:** https://github.com/bambulab/BambuStudio/issues
