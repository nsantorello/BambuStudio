#!/usr/bin/env python3
"""
Render 3MF files to PNG thumbnails with customizable colors.
Uses software rendering via trimesh and PIL.
"""

import argparse
import zipfile
import os
import sys
import json
import numpy as np
from PIL import Image

try:
    import trimesh
except ImportError:
    print("Please install trimesh: pip install trimesh")
    sys.exit(1)


def load_3mf_meshes(filepath):
    """Load meshes from a 3MF file."""
    meshes = []

    # 3MF files are ZIP archives
    with zipfile.ZipFile(filepath, 'r') as z:
        # Look for model files
        for name in z.namelist():
            if name.endswith('.model') or name.endswith('.3dmodel'):
                continue  # Skip XML model definition files

        # Use trimesh to load the 3MF directly
        try:
            scene = trimesh.load(filepath, force='scene')
            if isinstance(scene, trimesh.Scene):
                for name, geom in scene.geometry.items():
                    if isinstance(geom, trimesh.Trimesh):
                        meshes.append(geom)
            elif isinstance(scene, trimesh.Trimesh):
                meshes.append(scene)
        except Exception as e:
            print(f"Error loading 3MF: {e}")

    return meshes


def hex_to_rgba(hex_color):
    """Convert hex color to RGBA tuple (0-255 range)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        a = 255
    elif len(hex_color) == 8:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        a = int(hex_color[6:8], 16)
    else:
        r, g, b, a = 128, 128, 128, 255
    return (r, g, b, a)


def render_mesh_simple(meshes, colors, width=512, height=512, camera_angle='iso'):
    """
    Render meshes to an image using simple orthographic projection.
    This is a basic software renderer.
    """
    # Create output image
    img = Image.new('RGBA', (width, height), (240, 240, 240, 255))  # Light gray background
    pixels = np.array(img)

    # Initialize z-buffer
    z_buffer = np.full((height, width), float('inf'))

    if not meshes:
        return img

    # Combine all meshes and find bounds
    all_vertices = []
    all_faces = []
    all_face_colors = []
    vertex_offset = 0

    for i, mesh in enumerate(meshes):
        color = hex_to_rgba(colors[i % len(colors)] if colors else '#00AE42')

        all_vertices.append(mesh.vertices)
        all_faces.append(mesh.faces + vertex_offset)
        all_face_colors.extend([color] * len(mesh.faces))
        vertex_offset += len(mesh.vertices)

    if not all_vertices:
        return img

    vertices = np.vstack(all_vertices)
    faces = np.vstack(all_faces)

    # Center the model
    center = (vertices.max(axis=0) + vertices.min(axis=0)) / 2
    vertices = vertices - center

    # Calculate scale to fit in view
    max_dim = np.abs(vertices).max()
    if max_dim > 0:
        scale = (min(width, height) * 0.4) / max_dim
    else:
        scale = 1.0

    vertices *= scale

    # Apply rotation based on camera angle
    if camera_angle == 'iso':
        # Isometric view: rotate around Y then X
        angle_y = np.radians(45)
        angle_x = np.radians(35.264)  # atan(1/sqrt(2))

        # Rotation around Y axis
        cos_y, sin_y = np.cos(angle_y), np.sin(angle_y)
        rot_y = np.array([
            [cos_y, 0, sin_y],
            [0, 1, 0],
            [-sin_y, 0, cos_y]
        ])

        # Rotation around X axis
        cos_x, sin_x = np.cos(angle_x), np.sin(angle_x)
        rot_x = np.array([
            [1, 0, 0],
            [0, cos_x, -sin_x],
            [0, sin_x, cos_x]
        ])

        vertices = vertices @ rot_y.T @ rot_x.T
    elif camera_angle == 'top':
        # Top view: rotate 90 degrees around X
        angle_x = np.radians(-90)
        cos_x, sin_x = np.cos(angle_x), np.sin(angle_x)
        rot_x = np.array([
            [1, 0, 0],
            [0, cos_x, -sin_x],
            [0, sin_x, cos_x]
        ])
        vertices = vertices @ rot_x.T
    elif camera_angle == 'front':
        pass  # No rotation needed
    elif camera_angle == 'left':
        angle_y = np.radians(90)
        cos_y, sin_y = np.cos(angle_y), np.sin(angle_y)
        rot_y = np.array([
            [cos_y, 0, sin_y],
            [0, 1, 0],
            [-sin_y, 0, cos_y]
        ])
        vertices = vertices @ rot_y.T
    elif camera_angle == 'right':
        angle_y = np.radians(-90)
        cos_y, sin_y = np.cos(angle_y), np.sin(angle_y)
        rot_y = np.array([
            [cos_y, 0, sin_y],
            [0, 1, 0],
            [-sin_y, 0, cos_y]
        ])
        vertices = vertices @ rot_y.T

    # Project to 2D (orthographic projection)
    proj_vertices = np.zeros((len(vertices), 2))
    proj_vertices[:, 0] = vertices[:, 0] + width / 2
    proj_vertices[:, 1] = -vertices[:, 1] + height / 2  # Flip Y

    # Light direction for simple shading
    light_dir = np.array([0.5, 0.5, 1.0])
    light_dir = light_dir / np.linalg.norm(light_dir)

    # Sort faces by depth (painter's algorithm)
    face_depths = []
    for face in faces:
        depth = vertices[face, 2].mean()
        face_depths.append(depth)

    sorted_indices = np.argsort(face_depths)[::-1]  # Back to front

    # Draw faces
    from PIL import ImageDraw
    img_draw = Image.new('RGBA', (width, height), (240, 240, 240, 255))
    draw = ImageDraw.Draw(img_draw)

    for idx in sorted_indices:
        face = faces[idx]
        color = all_face_colors[idx]

        # Get triangle vertices
        v0, v1, v2 = vertices[face]
        p0 = (int(proj_vertices[face[0], 0]), int(proj_vertices[face[0], 1]))
        p1 = (int(proj_vertices[face[1], 0]), int(proj_vertices[face[1], 1]))
        p2 = (int(proj_vertices[face[2], 0]), int(proj_vertices[face[2], 1]))

        # Calculate face normal for shading
        edge1 = v1 - v0
        edge2 = v2 - v0
        normal = np.cross(edge1, edge2)
        norm_len = np.linalg.norm(normal)
        if norm_len > 0:
            normal = normal / norm_len
        else:
            normal = np.array([0, 0, 1])

        # Simple diffuse shading
        intensity = max(0.3, min(1.0, np.dot(normal, light_dir) * 0.7 + 0.3))

        # Apply shading to color
        shaded_color = (
            int(color[0] * intensity),
            int(color[1] * intensity),
            int(color[2] * intensity),
            color[3]
        )

        # Draw filled triangle
        draw.polygon([p0, p1, p2], fill=shaded_color)

    return img_draw


def main():
    parser = argparse.ArgumentParser(description='Render 3MF files to PNG thumbnails')
    parser.add_argument('input', help='Input 3MF file')
    parser.add_argument('-o', '--output', help='Output PNG file', default='output.png')
    parser.add_argument('-c', '--colors', nargs='+', help='Hex colors for objects (e.g., #FF0000 #00FF00)',
                        default=['#00AE42'])
    parser.add_argument('-w', '--width', type=int, default=512, help='Output width in pixels')
    parser.add_argument('-H', '--height', type=int, default=512, help='Output height in pixels')
    parser.add_argument('-a', '--angle', choices=['iso', 'top', 'front', 'left', 'right'],
                        default='iso', help='Camera angle')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found")
        sys.exit(1)

    print(f"Loading 3MF file: {args.input}")
    meshes = load_3mf_meshes(args.input)

    if not meshes:
        print("No meshes found in 3MF file")
        sys.exit(1)

    print(f"Found {len(meshes)} mesh(es)")
    print(f"Using colors: {args.colors}")
    print(f"Rendering at {args.width}x{args.height} with {args.angle} view...")

    img = render_mesh_simple(meshes, args.colors, args.width, args.height, args.angle)

    print(f"Saving to: {args.output}")
    img.save(args.output)
    print("Done!")


if __name__ == '__main__':
    main()
