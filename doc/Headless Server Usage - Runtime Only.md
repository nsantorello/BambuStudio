# Bambu Studio Headless Server Usage - Runtime Only (Official Binaries)

## Overview

This guide shows how to run **official Bambu Studio binaries** on headless Linux servers without rebuilding. These methods work with pre-compiled releases and don't require source code modifications.

## Method 1: Xvfb (Recommended)

**Xvfb** (X Virtual Framebuffer) creates a virtual display that doesn't require actual hardware. This is the most reliable method for official binaries.

### Installation

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y xvfb mesa-utils
```

**RHEL/CentOS/Fedora:**
```bash
sudo dnf install -y xorg-x11-server-Xvfb mesa-dri-drivers
```

### Usage Option A: xvfb-run (Easiest)

The `xvfb-run` wrapper automatically manages the virtual display:

```bash
xvfb-run -a ./bambu-studio-console \
    --slice \
    --load config.ini \
    --output output.gcode \
    model.3mf
```

**Explanation:**
- `-a` : Automatically pick an available display number
- `-s "-screen 0 1024x768x24"` : Optional, set virtual screen size and color depth

### Usage Option B: Manual Xvfb Control

For more control or persistent virtual displays:

```bash
# Start Xvfb on display :99 in the background
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!

# Wait for it to start
sleep 1

# Run Bambu Studio with the virtual display
DISPLAY=:99 ./bambu-studio-console \
    --slice \
    --load config.ini \
    --output output.gcode \
    model.3mf

# Clean up
kill $XVFB_PID
```

### Usage Option C: Systemd Service (Production Servers)

For production environments, run Xvfb as a persistent service:

**Create `/etc/systemd/system/xvfb.service`:**
```ini
[Unit]
Description=X Virtual Frame Buffer Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable xvfb
sudo systemctl start xvfb
```

**Use in scripts:**
```bash
export DISPLAY=:99
./bambu-studio-console --slice ...
```

## Method 2: Docker with Xvfb

Perfect for containerized environments:

```dockerfile
FROM ubuntu:22.04

# Install Xvfb and dependencies
RUN apt-get update && apt-get install -y \
    xvfb \
    mesa-utils \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libglu1-mesa \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Download official Bambu Studio binary
RUN wget -O /tmp/bambu-studio.deb https://example.com/bambu-studio.deb && \
    apt-get install -y /tmp/bambu-studio.deb && \
    rm /tmp/bambu-studio.deb

# Create wrapper script
RUN echo '#!/bin/bash\nxvfb-run -a /usr/bin/bambu-studio-console "$@"' > /usr/local/bin/slice && \
    chmod +x /usr/local/bin/slice

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/slice"]
```

**Usage:**
```bash
docker build -t bambu-slicer .
docker run --rm -v $(pwd):/workspace bambu-slicer \
    --slice --load config.ini --output output.gcode model.3mf
```

## Method 3: Screen Recording Driver (Alternative)

If Xvfb doesn't work, try the dummy video driver:

```bash
# Install dummy driver
sudo apt-get install xserver-xorg-video-dummy

# Create minimal X config
cat > /tmp/xorg.conf << 'EOF'
Section "Device"
    Identifier "dummy"
    Driver "dummy"
    VideoRam 256000
EndSection

Section "Screen"
    Identifier "dummy_screen"
    Device "dummy"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1920x1080"
    EndSubSection
EndSection
EOF

# Start X with dummy driver
X :99 -config /tmp/xorg.conf &
X_PID=$!
sleep 2

# Run Bambu Studio
DISPLAY=:99 ./bambu-studio-console --slice ...

# Cleanup
kill $X_PID
```

## Verification

### Check if Thumbnails are Generated

After slicing, verify thumbnails were embedded:

**For G-code files:**
```bash
# Look for thumbnail data in comments
head -n 100 output.gcode | grep -i thumbnail
```

You should see lines like:
```
; thumbnail begin 300x300 ...
```

**For 3MF files:**
```bash
# 3MF files are ZIP archives
unzip -l output.3mf | grep -i thumbnail
```

You should see files like:
```
Metadata/plate_1_thumbnail.png
Metadata/plate_1_top_thumbnail.png
```

### Check Xvfb is Working

```bash
# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!
sleep 1

# Test OpenGL
DISPLAY=:99 glxinfo | grep "OpenGL"

# Should show software rendering info
# OpenGL vendor string: VMware, Inc.
# OpenGL renderer string: llvmpipe (LLVM ...)

kill $XVFB_PID
```

## Comparison: Build vs Runtime Solutions

| Aspect | OSMesa (Rebuild) | Xvfb (Runtime) |
|--------|------------------|----------------|
| **Requires rebuild** | Yes | No |
| **Works with official binaries** | No | Yes |
| **Performance** | Slower (software) | Slower (software) |
| **Memory usage** | Lower | Higher (X server) |
| **Complexity** | High | Low |
| **Maintenance** | Must rebuild on updates | Just update binary |
| **Production ready** | Yes | Yes |

**Recommendation:** Use **Xvfb** for official binaries - it's simpler and doesn't require rebuilding.

## Automation Scripts

### Bash Script for Batch Processing

```bash
#!/bin/bash
# batch-slice.sh - Process multiple 3MF files with thumbnails

INPUT_DIR="$1"
OUTPUT_DIR="$2"
CONFIG="$3"

if [ -z "$INPUT_DIR" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$CONFIG" ]; then
    echo "Usage: $0 <input_dir> <output_dir> <config.ini>"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Process each 3MF file
for model in "$INPUT_DIR"/*.3mf; do
    filename=$(basename "$model" .3mf)
    echo "Processing $filename..."

    xvfb-run -a ./bambu-studio-console \
        --slice \
        --load "$CONFIG" \
        --output "$OUTPUT_DIR/${filename}.gcode" \
        "$model"

    if [ $? -eq 0 ]; then
        echo "✓ $filename completed"
    else
        echo "✗ $filename failed"
    fi
done

echo "Batch processing complete!"
```

**Usage:**
```bash
chmod +x batch-slice.sh
./batch-slice.sh ./models ./output printer-config.ini
```

### Python Script with Error Handling

```python
#!/usr/bin/env python3
"""
slice-server.py - Automated slicing with Xvfb
"""
import subprocess
import sys
from pathlib import Path

def slice_with_thumbnails(model_path, config_path, output_path):
    """Slice a 3MF file with thumbnail generation using Xvfb"""

    cmd = [
        'xvfb-run', '-a',
        './bambu-studio-console',
        '--slice',
        '--load', str(config_path),
        '--output', str(output_path),
        str(model_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            print(f"✓ Sliced: {model_path} -> {output_path}")

            # Verify thumbnail
            if output_path.suffix == '.gcode':
                with open(output_path, 'r') as f:
                    content = f.read(5000)  # Check first 5KB
                    if 'thumbnail' in content.lower():
                        print("  ✓ Thumbnail embedded")
                    else:
                        print("  ⚠ No thumbnail found (may be OK)")
            return True
        else:
            print(f"✗ Failed: {model_path}")
            print(f"  Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"✗ Timeout: {model_path}")
        return False
    except Exception as e:
        print(f"✗ Error: {model_path} - {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: slice-server.py <model.3mf> <config.ini> <output.gcode>")
        sys.exit(1)

    success = slice_with_thumbnails(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        Path(sys.argv[3])
    )

    sys.exit(0 if success else 1)
```

## Troubleshooting

### Error: "cannot open display"

**Cause:** Xvfb not running or DISPLAY not set

**Solution:**
```bash
# Check if Xvfb is running
ps aux | grep Xvfb

# If not, start it
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
```

### Error: "Failed to initialize OpenGL"

**Cause:** Missing Mesa drivers

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get install mesa-utils libgl1-mesa-dri libgl1-mesa-glx

# Test
DISPLAY=:99 glxinfo | head -20
```

### Thumbnails Still Not Generated

**Possible causes:**
1. Check logs for OpenGL errors
2. Verify display is accessible: `echo $DISPLAY`
3. Test with verbose logging:
```bash
DISPLAY=:99 LIBGL_DEBUG=verbose ./bambu-studio-console --slice ...
```

### High Memory Usage

**Cause:** Xvfb allocates virtual screen memory

**Solution:** Reduce virtual screen size:
```bash
# Instead of 1920x1080
Xvfb :99 -screen 0 800x600x24 &
```

Thumbnails don't need large resolution - 800x600 is sufficient.

## Performance Tips

1. **Persistent Xvfb:** Start once, reuse for multiple slicing jobs
2. **Display number:** Use unique display numbers for parallel jobs (`:99`, `:100`, etc.)
3. **Screen size:** Smaller virtual screens use less memory
4. **Cleanup:** Kill Xvfb processes after batch jobs complete

## Security Considerations

1. **X11 Security:** Xvfb runs with `-ac` (disable access control) - isolate in containers/VMs
2. **Display numbers:** Use high numbers (`:99`+) to avoid conflicts with real displays
3. **Temporary files:** Xvfb creates `/tmp/.X*` files - clean up in automation
4. **User permissions:** Run as non-root user when possible

## Production Example: Kubernetes Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: bambu-slicer-job
spec:
  template:
    spec:
      containers:
      - name: slicer
        image: bambu-slicer:latest
        command: ["/bin/bash", "-c"]
        args:
          - |
            Xvfb :99 -screen 0 1024x768x24 &
            sleep 2
            export DISPLAY=:99
            /usr/bin/bambu-studio-console \
              --slice \
              --load /config/printer.ini \
              --output /output/model.gcode \
              /input/model.3mf
        volumeMounts:
        - name: input
          mountPath: /input
        - name: output
          mountPath: /output
        - name: config
          mountPath: /config
      restartPolicy: Never
      volumes:
      - name: input
        persistentVolumeClaim:
          claimName: models-pvc
      - name: output
        persistentVolumeClaim:
          claimName: output-pvc
      - name: config
        configMap:
          name: slicer-config
```

## Conclusion

**For official Bambu Studio binaries, use Xvfb** - it's:
- ✅ No rebuild required
- ✅ Works with any release version
- ✅ Production-tested solution
- ✅ Easy to automate
- ✅ Container-friendly

The OSMesa approach (see `Headless Server Usage.md`) is only needed if you're building from source and want to eliminate the X server dependency entirely.

## Additional Resources

- Xvfb documentation: `man Xvfb`
- Testing OpenGL: `glxinfo` and `glxgears`
- X11 troubleshooting: `/var/log/Xorg.*.log`
- Bambu Studio CLI help: `./bambu-studio-console --help`
