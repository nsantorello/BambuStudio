#!/usr/bin/env python3
"""
Headless Thumbnail Renderer for BambuStudio

This script renders 3D model thumbnails in a headless environment (no GPU required)
using software rendering (OSMesa/LLVMpipe). It replicates the lighting and style
from BambuStudio's thumbnail rendering.

Supported formats: STL, 3MF, STEP (requires cadquery or OCP for STEP)

Usage:
    python headless_thumbnail.py model.stl -o thumbnail.png
    python headless_thumbnail.py model.3mf -o thumbnail.png --size 512
    python headless_thumbnail.py model.step -o thumbnail.png --view iso
"""

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple, List

# Check for required dependencies before proceeding
def _check_dependencies():
    """Check for required dependencies and provide helpful error messages."""
    missing = []

    try:
        import numpy
    except ImportError:
        missing.append('numpy')

    try:
        import trimesh
    except ImportError:
        missing.append('trimesh')

    try:
        from PIL import Image
    except ImportError:
        missing.append('Pillow')

    if missing:
        print("Error: Missing required dependencies:", file=sys.stderr)
        print(f"  {', '.join(missing)}", file=sys.stderr)
        print("\nInstall them with:", file=sys.stderr)
        print(f"  pip install {' '.join(missing)}", file=sys.stderr)
        print("\nOr install all requirements:", file=sys.stderr)
        print("  pip install -r scripts/requirements-thumbnail.txt", file=sys.stderr)
        sys.exit(1)

# Check dependencies immediately when script is run
_check_dependencies()

import numpy as np

# Set environment variables for software rendering BEFORE importing OpenGL
os.environ['PYOPENGL_PLATFORM'] = 'osmesa'
os.environ['MESA_GL_VERSION_OVERRIDE'] = '3.3'
os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'

import trimesh
from PIL import Image

# Lighting constants from BambuStudio (src/resources/shaders/140/thumbnail.vs)
INTENSITY_CORRECTION = 0.6

# Top light - normalized direction: (-0.6/1.31, 0.6/1.31, 1./1.31)
LIGHT_TOP_DIR = np.array([-0.4574957, 0.4574957, 0.7624929])
LIGHT_TOP_DIFFUSE = 0.8 * INTENSITY_CORRECTION  # 0.48
LIGHT_TOP_SPECULAR = 0.125 * INTENSITY_CORRECTION  # 0.075
LIGHT_TOP_SHININESS = 20.0

# Front light - normalized direction: (1./1.43, 0.2/1.43, 1./1.43)
LIGHT_FRONT_DIR = np.array([0.6985074, 0.1397015, 0.6985074])
LIGHT_FRONT_DIFFUSE = 0.3 * INTENSITY_CORRECTION  # 0.18

INTENSITY_AMBIENT = 0.3
EMISSION_FACTOR = 0.1

# Default model color (BambuStudio NEUTRAL_COLOR)
DEFAULT_COLOR = np.array([0.8, 0.8, 0.8, 1.0])


class ViewAngles:
    """Camera view angles matching BambuStudio's Camera::ViewAngleType"""
    ISO = 'iso'
    TOP_FRONT = 'top_front'
    LEFT = 'left'
    RIGHT = 'right'
    TOP = 'top'
    BOTTOM = 'bottom'
    FRONT = 'front'
    REAR = 'rear'
    ISO_1 = 'iso_1'  # 90 degrees clockwise from iso
    ISO_2 = 'iso_2'  # 180 degrees from iso
    ISO_3 = 'iso_3'  # 270 degrees clockwise from iso


def get_camera_transform(view: str, bounds: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Get camera position and target based on view angle.
    Returns (camera_position, camera_target).

    Camera positions are designed to match BambuStudio's view angles.
    """
    center = (bounds[0] + bounds[1]) / 2
    size = bounds[1] - bounds[0]
    max_dim = np.max(size)
    distance = max_dim * 2.5

    # Define view transformations
    views = {
        ViewAngles.ISO: np.array([1, -1, 0.8]),
        ViewAngles.ISO_1: np.array([1, 1, 0.8]),
        ViewAngles.ISO_2: np.array([-1, 1, 0.8]),
        ViewAngles.ISO_3: np.array([-1, -1, 0.8]),
        ViewAngles.TOP_FRONT: np.array([0, -0.3, 1]),
        ViewAngles.LEFT: np.array([-1, 0, 0]),
        ViewAngles.RIGHT: np.array([1, 0, 0]),
        ViewAngles.TOP: np.array([0, 0, 1]),
        ViewAngles.BOTTOM: np.array([0, 0, -1]),
        ViewAngles.FRONT: np.array([0, -1, 0]),
        ViewAngles.REAR: np.array([0, 1, 0]),
    }

    direction = views.get(view, views[ViewAngles.ISO])
    direction = direction / np.linalg.norm(direction)
    camera_pos = center + direction * distance

    return camera_pos, center


def compute_lighting(normals: np.ndarray, view_matrix: np.ndarray,
                     base_color: np.ndarray) -> np.ndarray:
    """
    Compute per-vertex colors using BambuStudio's lighting model.

    This implements the lighting calculation from thumbnail.vs:
    - Two directional lights (top and front)
    - Ambient lighting
    - Specular highlights for top light
    - Emission factor
    """
    # Transform normals to view space
    rotation = view_matrix[:3, :3]
    view_normals = np.dot(normals, rotation.T)

    # Normalize
    norms = np.linalg.norm(view_normals, axis=1, keepdims=True)
    norms = np.where(norms > 0, norms, 1)
    view_normals = view_normals / norms

    # Top light diffuse
    n_dot_l_top = np.maximum(np.dot(view_normals, LIGHT_TOP_DIR), 0)
    diffuse = INTENSITY_AMBIENT + n_dot_l_top * LIGHT_TOP_DIFFUSE

    # Front light diffuse
    n_dot_l_front = np.maximum(np.dot(view_normals, LIGHT_FRONT_DIR), 0)
    diffuse += n_dot_l_front * LIGHT_FRONT_DIFFUSE

    # Specular (simplified - from top light only)
    # In the shader this uses view position, here we approximate
    view_dir = np.array([0, 0, 1])  # Looking down -Z in view space
    reflect_dir = 2 * n_dot_l_top[:, np.newaxis] * view_normals - LIGHT_TOP_DIR
    r_dot_v = np.maximum(np.dot(reflect_dir, view_dir), 0)
    specular = LIGHT_TOP_SPECULAR * np.power(r_dot_v, LIGHT_TOP_SHININESS)

    # Combine: specular + color * (diffuse + emission)
    rgb = base_color[:3]
    intensity = diffuse + EMISSION_FACTOR

    # Apply lighting to color
    vertex_colors = np.zeros((len(normals), 4))
    vertex_colors[:, :3] = specular[:, np.newaxis] + rgb * intensity[:, np.newaxis]
    vertex_colors[:, 3] = base_color[3]

    # Clamp to valid range
    vertex_colors = np.clip(vertex_colors, 0, 1)

    return vertex_colors


def load_model(filepath: str) -> trimesh.Trimesh:
    """
    Load a 3D model from file. Supports STL, 3MF, and STEP formats.
    """
    ext = Path(filepath).suffix.lower()

    if ext == '.stl':
        mesh = trimesh.load(filepath, force='mesh')
    elif ext == '.3mf':
        mesh = load_3mf(filepath)
    elif ext in ['.step', '.stp']:
        mesh = load_step(filepath)
    else:
        # Try generic loading
        mesh = trimesh.load(filepath, force='mesh')

    # Ensure we have a single mesh
    if isinstance(mesh, trimesh.Scene):
        meshes = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if meshes:
            mesh = trimesh.util.concatenate(meshes)
        else:
            raise ValueError(f"No valid mesh geometry found in {filepath}")

    return mesh


def load_3mf(filepath: str) -> trimesh.Trimesh:
    """Load a 3MF file and extract meshes."""
    meshes = []

    with zipfile.ZipFile(filepath, 'r') as zf:
        # Find model files in the 3MF archive
        model_files = [n for n in zf.namelist() if n.endswith('.model')]

        if not model_files:
            # Fallback to trimesh's 3MF loader
            return trimesh.load(filepath, force='mesh')

        # Extract to temp and load
        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)

            # Try trimesh's native 3MF support
            try:
                scene = trimesh.load(filepath)
                if isinstance(scene, trimesh.Scene):
                    meshes = [g for g in scene.geometry.values()
                              if isinstance(g, trimesh.Trimesh)]
                    if meshes:
                        return trimesh.util.concatenate(meshes)
                elif isinstance(scene, trimesh.Trimesh):
                    return scene
            except Exception:
                pass

            # Fallback: look for STL files extracted
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.lower().endswith('.stl'):
                        try:
                            m = trimesh.load(os.path.join(root, f), force='mesh')
                            if isinstance(m, trimesh.Trimesh):
                                meshes.append(m)
                        except Exception:
                            continue

    if meshes:
        return trimesh.util.concatenate(meshes)

    # Final fallback
    return trimesh.load(filepath, force='mesh')


def load_step(filepath: str) -> trimesh.Trimesh:
    """
    Load a STEP file. Requires cadquery or OCP (OpenCascade Python bindings).
    """
    meshes = []

    # Try cadquery first (most common)
    try:
        import cadquery as cq
        from cadquery import exporters

        # Load STEP and convert to mesh
        result = cq.importers.importStep(filepath)

        # Export to temporary STL and reload
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            exporters.export(result, tmp_path, exportType='STL', tolerance=0.1)
            mesh = trimesh.load(tmp_path, force='mesh')
            return mesh
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except ImportError:
        pass

    # Try OCP directly
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopLoc import TopLoc_Location
        from OCP.BRep import BRep_Tool
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE
        from OCP.gp import gp_Trsf

        reader = STEPControl_Reader()
        reader.ReadFile(filepath)
        reader.TransferRoots()
        shape = reader.OneShape()

        # Mesh the shape
        BRepMesh_IncrementalMesh(shape, 0.1)

        # Extract triangles
        vertices = []
        faces = []
        vertex_offset = 0

        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            loc = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, loc)

            if triangulation is not None:
                # Get transformation
                trsf = loc.Transformation()

                # Get vertices
                for i in range(1, triangulation.NbNodes() + 1):
                    pnt = triangulation.Node(i)
                    pnt.Transform(trsf)
                    vertices.append([pnt.X(), pnt.Y(), pnt.Z()])

                # Get triangles
                for i in range(1, triangulation.NbTriangles() + 1):
                    tri = triangulation.Triangle(i)
                    i1, i2, i3 = tri.Get()
                    faces.append([i1 - 1 + vertex_offset,
                                  i2 - 1 + vertex_offset,
                                  i3 - 1 + vertex_offset])

                vertex_offset += triangulation.NbNodes()

            explorer.Next()

        if vertices and faces:
            mesh = trimesh.Trimesh(vertices=np.array(vertices),
                                   faces=np.array(faces))
            return mesh

    except ImportError:
        pass

    # Try trimesh's native STEP support (if available)
    try:
        mesh = trimesh.load(filepath, force='mesh')
        return mesh
    except Exception:
        pass

    raise ImportError(
        "STEP file loading requires 'cadquery' or 'OCP' package.\n"
        "Install with: pip install cadquery\n"
        "Or for OCP: pip install OCP"
    )


def create_view_matrix(camera_pos: np.ndarray, target: np.ndarray,
                       up: np.ndarray = np.array([0, 0, 1])) -> np.ndarray:
    """Create a view matrix (look-at matrix)."""
    forward = target - camera_pos
    forward = forward / np.linalg.norm(forward)

    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-6:
        up = np.array([0, 1, 0])
        right = np.cross(forward, up)
    right = right / np.linalg.norm(right)

    up = np.cross(right, forward)
    up = up / np.linalg.norm(up)

    view_matrix = np.eye(4)
    view_matrix[0, :3] = right
    view_matrix[1, :3] = up
    view_matrix[2, :3] = -forward
    view_matrix[:3, 3] = -np.dot(view_matrix[:3, :3], camera_pos)

    return view_matrix


def create_ortho_matrix(left: float, right: float, bottom: float, top: float,
                        near: float, far: float) -> np.ndarray:
    """Create an orthographic projection matrix."""
    proj = np.zeros((4, 4))
    proj[0, 0] = 2 / (right - left)
    proj[1, 1] = 2 / (top - bottom)
    proj[2, 2] = -2 / (far - near)
    proj[0, 3] = -(right + left) / (right - left)
    proj[1, 3] = -(top + bottom) / (top - bottom)
    proj[2, 3] = -(far + near) / (far - near)
    proj[3, 3] = 1
    return proj


def rasterize_triangle(v0, v1, v2, color, image, zbuffer, width, height):
    """Rasterize a single triangle using scanline algorithm."""
    # Compute bounding box
    min_x = max(0, int(min(v0[0], v1[0], v2[0])))
    max_x = min(width - 1, int(max(v0[0], v1[0], v2[0])))
    min_y = max(0, int(min(v0[1], v1[1], v2[1])))
    max_y = min(height - 1, int(max(v0[1], v1[1], v2[1])))

    if min_x > max_x or min_y > max_y:
        return

    # Compute edge vectors for barycentric coordinates
    v0v1 = v1[:2] - v0[:2]
    v0v2 = v2[:2] - v0[:2]
    denom = v0v1[0] * v0v2[1] - v0v1[1] * v0v2[0]

    if abs(denom) < 1e-10:
        return  # Degenerate triangle

    inv_denom = 1.0 / denom

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            # Compute barycentric coordinates
            v0p = np.array([x - v0[0], y - v0[1]])
            u = (v0p[0] * v0v2[1] - v0p[1] * v0v2[0]) * inv_denom
            v = (v0v1[0] * v0p[1] - v0v1[1] * v0p[0]) * inv_denom

            if u >= 0 and v >= 0 and (u + v) <= 1:
                # Interpolate z
                z = v0[2] * (1 - u - v) + v1[2] * u + v2[2] * v

                # Z-buffer test
                if z > zbuffer[y, x]:
                    zbuffer[y, x] = z
                    image[y, x] = color


def render_thumbnail_numpy(mesh: trimesh.Trimesh,
                           width: int = 512,
                           height: int = 512,
                           view: str = ViewAngles.ISO,
                           color: Optional[np.ndarray] = None,
                           background: Optional[Tuple[int, int, int, int]] = None,
                           transparent: bool = True) -> Image.Image:
    """
    Render a thumbnail using pure numpy software rasterization.
    No OpenGL or external rendering libraries required.
    """
    if color is None:
        color = DEFAULT_COLOR.copy()

    # Get camera setup
    bounds = mesh.bounds
    camera_pos, target = get_camera_transform(view, bounds)
    center = (bounds[0] + bounds[1]) / 2
    size = bounds[1] - bounds[0]
    max_dim = np.max(size)

    # Create view matrix
    view_matrix = create_view_matrix(camera_pos, target)

    # Create orthographic projection
    scale = max_dim * 0.6
    aspect = width / height
    proj_matrix = create_ortho_matrix(-scale * aspect, scale * aspect,
                                       -scale, scale,
                                       -max_dim * 5, max_dim * 5)

    # Combined MVP matrix
    mvp = proj_matrix @ view_matrix

    # Transform vertices
    vertices = mesh.vertices
    ones = np.ones((len(vertices), 1))
    vertices_h = np.hstack([vertices, ones])
    transformed = (mvp @ vertices_h.T).T

    # Perspective divide (for ortho, w=1)
    w = transformed[:, 3:4]
    w[w == 0] = 1
    ndc = transformed[:, :3] / w

    # Convert to screen coordinates
    screen_x = (ndc[:, 0] + 1) * 0.5 * width
    screen_y = (1 - ndc[:, 1]) * 0.5 * height  # Flip Y
    screen_z = ndc[:, 2]

    screen_coords = np.column_stack([screen_x, screen_y, screen_z])

    # Compute face normals in view space for lighting
    if mesh.face_normals is None or len(mesh.face_normals) == 0:
        mesh.fix_normals()

    face_normals = mesh.face_normals
    face_colors = compute_lighting(face_normals, view_matrix, color)

    # Initialize buffers
    if transparent and background is None:
        image = np.zeros((height, width, 4), dtype=np.uint8)
    else:
        bg = background if background else (255, 255, 255, 255)
        image = np.full((height, width, 4), bg, dtype=np.uint8)

    zbuffer = np.full((height, width), -np.inf)

    # Get faces sorted by depth (painter's algorithm backup)
    faces = mesh.faces
    face_centers = mesh.vertices[faces].mean(axis=1)
    face_centers_h = np.hstack([face_centers, np.ones((len(face_centers), 1))])
    face_depths = (view_matrix @ face_centers_h.T)[2, :]
    sorted_indices = np.argsort(face_depths)

    # Rasterize each triangle
    print(f"Rasterizing {len(faces)} triangles...", file=sys.stderr)
    for i, face_idx in enumerate(sorted_indices):
        if i % 10000 == 0:
            print(f"  Progress: {i}/{len(faces)} ({100*i/len(faces):.1f}%)", file=sys.stderr)

        face = faces[face_idx]
        v0 = screen_coords[face[0]]
        v1 = screen_coords[face[1]]
        v2 = screen_coords[face[2]]

        # Back-face culling (screen Y is flipped, so sign is reversed)
        edge1 = v1[:2] - v0[:2]
        edge2 = v2[:2] - v0[:2]
        cross = edge1[0] * edge2[1] - edge1[1] * edge2[0]
        if cross > 0:  # Back-facing in screen space (Y is flipped)
            continue

        # Get face color
        fc = face_colors[face_idx]
        fc_int = (np.clip(fc, 0, 1) * 255).astype(np.uint8)

        rasterize_triangle(v0, v1, v2, fc_int, image, zbuffer, width, height)

    print(f"  Progress: {len(faces)}/{len(faces)} (100.0%)", file=sys.stderr)
    return Image.fromarray(image)


def render_thumbnail_software(mesh: trimesh.Trimesh,
                              width: int = 512,
                              height: int = 512,
                              view: str = ViewAngles.ISO,
                              color: Optional[np.ndarray] = None,
                              background: Optional[Tuple[int, int, int, int]] = None,
                              transparent: bool = True) -> Image.Image:
    """
    Render a thumbnail using software rasterization.
    Tries trimesh's renderer first, falls back to pure numpy.
    """
    if color is None:
        color = DEFAULT_COLOR.copy()

    # Get camera setup
    bounds = mesh.bounds
    camera_pos, target = get_camera_transform(view, bounds)

    # Create view matrix
    view_matrix = create_view_matrix(camera_pos, target)

    # Compute lighting
    if mesh.vertex_normals is None or len(mesh.vertex_normals) == 0:
        mesh.fix_normals()

    # Use face normals for flat shading
    face_normals = mesh.face_normals

    # Compute colors per face
    face_colors = compute_lighting(face_normals, view_matrix, color)

    # Apply colors to mesh
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        face_colors=(face_colors * 255).astype(np.uint8)
    )

    # Create scene for rendering
    scene = trimesh.Scene(mesh)

    # Set camera
    center = (bounds[0] + bounds[1]) / 2
    size = bounds[1] - bounds[0]
    max_dim = np.max(size)

    # Create camera transform
    camera_transform = np.linalg.inv(view_matrix)
    scene.camera_transform = camera_transform

    # Set orthographic camera
    scene.camera.fov = None  # Orthographic

    # Render using trimesh's built-in renderer
    try:
        # Try to render to PNG bytes
        png_data = scene.save_image(resolution=(width, height), visible=False)
        img = Image.open(trimesh.util.wrap_as_stream(png_data))

        if transparent and background is None:
            # Make white background transparent
            img = img.convert('RGBA')
            data = np.array(img)
            # Find near-white pixels and make transparent
            white_thresh = 250
            mask = (data[:, :, 0] > white_thresh) & \
                   (data[:, :, 1] > white_thresh) & \
                   (data[:, :, 2] > white_thresh)
            data[mask, 3] = 0
            img = Image.fromarray(data)

        return img

    except Exception as e:
        print(f"Trimesh rendering failed: {e}", file=sys.stderr)
        print("Falling back to numpy rasterizer...", file=sys.stderr)
        # Fall back to pure numpy rasterizer
        return render_thumbnail_numpy(mesh, width, height, view, color,
                                       background, transparent)


def render_thumbnail_pyrender(mesh: trimesh.Trimesh,
                              width: int = 512,
                              height: int = 512,
                              view: str = ViewAngles.ISO,
                              color: Optional[np.ndarray] = None,
                              background: Optional[Tuple[float, float, float, float]] = None,
                              transparent: bool = True) -> Image.Image:
    """
    Render a thumbnail using pyrender with OSMesa backend.
    This provides higher quality rendering with proper shading.
    """
    import pyrender

    if color is None:
        color = DEFAULT_COLOR.copy()

    # Get camera setup
    bounds = mesh.bounds
    camera_pos, target = get_camera_transform(view, bounds)
    center = (bounds[0] + bounds[1]) / 2
    size = bounds[1] - bounds[0]
    max_dim = np.max(size)

    # Create view matrix
    view_matrix = create_view_matrix(camera_pos, target)

    # Compute per-vertex lighting colors
    if mesh.vertex_normals is None or len(mesh.vertex_normals) != len(mesh.vertices):
        mesh.fix_normals()

    vertex_colors = compute_lighting(mesh.vertex_normals, view_matrix, color)

    # Create pyrender mesh with vertex colors
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        vertex_colors=(vertex_colors * 255).astype(np.uint8)
    )

    # Create pyrender scene
    scene = pyrender.Scene(bg_color=background if background else [0, 0, 0, 0],
                           ambient_light=[INTENSITY_AMBIENT] * 3)

    # Add mesh to scene
    # Use a simple material since we're doing our own lighting via vertex colors
    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=[1.0, 1.0, 1.0, 1.0],
        metallicFactor=0.0,
        roughnessFactor=1.0,
    )

    pyrender_mesh = pyrender.Mesh.from_trimesh(mesh, smooth=False)
    scene.add(pyrender_mesh)

    # Setup orthographic camera
    scale = max_dim * 0.6
    camera = pyrender.OrthographicCamera(xmag=scale, ymag=scale, znear=0.01, zfar=max_dim * 10)

    # Camera transform (inverse of view matrix, adjusted for pyrender conventions)
    camera_transform = np.linalg.inv(view_matrix)
    # Pyrender uses -Z as forward, we need to flip
    flip = np.eye(4)
    flip[1, 1] = -1
    flip[2, 2] = -1
    camera_transform = camera_transform @ flip

    scene.add(camera, pose=camera_transform)

    # Add lights matching BambuStudio configuration
    # Top directional light
    top_light = pyrender.DirectionalLight(
        color=[1.0, 1.0, 1.0],
        intensity=LIGHT_TOP_DIFFUSE * 2
    )
    top_light_pose = np.eye(4)
    top_light_pose[:3, 2] = -LIGHT_TOP_DIR
    scene.add(top_light, pose=top_light_pose)

    # Front directional light
    front_light = pyrender.DirectionalLight(
        color=[1.0, 1.0, 1.0],
        intensity=LIGHT_FRONT_DIFFUSE * 2
    )
    front_light_pose = np.eye(4)
    front_light_pose[:3, 2] = -LIGHT_FRONT_DIR
    scene.add(front_light, pose=front_light_pose)

    # Create offscreen renderer
    renderer = pyrender.OffscreenRenderer(width, height)

    try:
        # Render
        color_img, depth = renderer.render(scene,
                                           flags=pyrender.RenderFlags.RGBA if transparent
                                           else pyrender.RenderFlags.NONE)

        img = Image.fromarray(color_img)
        return img

    finally:
        renderer.delete()


def render_thumbnail(filepath: str,
                     output: str,
                     width: int = 512,
                     height: int = 512,
                     view: str = ViewAngles.ISO,
                     color: Optional[Tuple[float, float, float, float]] = None,
                     background: Optional[Tuple[int, int, int, int]] = None,
                     transparent: bool = True,
                     use_pyrender: bool = True) -> bool:
    """
    Main function to render a thumbnail from a 3D model file.

    Args:
        filepath: Path to the input 3D model (STL, 3MF, or STEP)
        output: Path to save the output PNG
        width: Output image width in pixels
        height: Output image height in pixels
        view: Camera view angle (iso, front, top, etc.)
        color: RGBA color for the model (0-1 range)
        background: RGBA background color (0-255 range)
        transparent: Whether to render with transparent background
        use_pyrender: Try to use pyrender for better quality

    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"Loading model: {filepath}")
        mesh = load_model(filepath)

        if mesh is None or len(mesh.vertices) == 0:
            print(f"Error: No valid mesh data in {filepath}", file=sys.stderr)
            return False

        print(f"Loaded mesh with {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")

        # Center the mesh
        mesh.vertices -= mesh.centroid

        # Prepare color
        if color:
            model_color = np.array(color)
        else:
            model_color = DEFAULT_COLOR.copy()

        # Prepare background
        bg = None
        if background:
            bg = tuple(b / 255.0 for b in background)
        elif not transparent:
            bg = (1.0, 1.0, 1.0, 1.0)

        # Try pyrender first for best quality
        img = None
        if use_pyrender:
            try:
                print("Rendering with pyrender/OSMesa...")
                img = render_thumbnail_pyrender(
                    mesh, width, height, view, model_color, bg, transparent
                )
            except Exception as e:
                print(f"Pyrender rendering failed: {e}", file=sys.stderr)
                print("Falling back to software rendering...", file=sys.stderr)

        # Fallback to trimesh software rendering
        if img is None:
            print("Rendering with software rasterizer...")
            img = render_thumbnail_software(
                mesh, width, height, view, model_color,
                tuple(int(b * 255) for b in bg) if bg else None,
                transparent
            )

        # Save the image
        print(f"Saving thumbnail to: {output}")
        img.save(output, 'PNG')

        return True

    except Exception as e:
        print(f"Error rendering thumbnail: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Render 3D model thumbnails in headless environment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s model.stl -o thumbnail.png
  %(prog)s model.3mf -o thumb.png --size 256
  %(prog)s model.step -o render.png --view front --color 0.2 0.6 0.9 1.0

View angles:
  iso       - Isometric view (default)
  iso_1     - Isometric rotated 90 degrees
  iso_2     - Isometric rotated 180 degrees
  iso_3     - Isometric rotated 270 degrees
  front     - Front view
  rear      - Rear view
  left      - Left side view
  right     - Right side view
  top       - Top view
  bottom    - Bottom view
  top_front - Top front view (for 3MF thumbnails)
        """
    )

    parser.add_argument('input', help='Input 3D model file (STL, 3MF, or STEP)')
    parser.add_argument('-o', '--output', required=True, help='Output PNG file')
    parser.add_argument('-s', '--size', type=int, default=512,
                        help='Output size in pixels (default: 512)')
    parser.add_argument('-W', '--width', type=int, default=None,
                        help='Output width (overrides --size)')
    parser.add_argument('-H', '--height', type=int, default=None,
                        help='Output height (overrides --size)')
    parser.add_argument('-v', '--view', default='iso',
                        choices=['iso', 'iso_1', 'iso_2', 'iso_3',
                                 'front', 'rear', 'left', 'right',
                                 'top', 'bottom', 'top_front'],
                        help='Camera view angle (default: iso)')
    parser.add_argument('-c', '--color', type=float, nargs=4,
                        metavar=('R', 'G', 'B', 'A'),
                        help='Model color as RGBA (0.0-1.0)')
    parser.add_argument('-b', '--background', type=int, nargs=4,
                        metavar=('R', 'G', 'B', 'A'),
                        help='Background color as RGBA (0-255)')
    parser.add_argument('--no-transparent', action='store_true',
                        help='Disable transparent background')
    parser.add_argument('--software-only', action='store_true',
                        help='Use software rendering only (no pyrender)')
    parser.add_argument('--batch', action='store_true',
                        help='Batch mode: render all views')

    args = parser.parse_args()

    # Validate input
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Determine dimensions
    width = args.width or args.size
    height = args.height or args.size

    # Handle batch mode
    if args.batch:
        views = ['iso', 'front', 'rear', 'left', 'right', 'top', 'bottom']
        base_output = Path(args.output)
        stem = base_output.stem
        suffix = base_output.suffix
        parent = base_output.parent

        success = True
        for view in views:
            output_path = parent / f"{stem}_{view}{suffix}"
            print(f"\n=== Rendering view: {view} ===")
            if not render_thumbnail(
                args.input,
                str(output_path),
                width, height,
                view,
                tuple(args.color) if args.color else None,
                tuple(args.background) if args.background else None,
                not args.no_transparent,
                not args.software_only
            ):
                success = False

        sys.exit(0 if success else 1)

    # Single render
    success = render_thumbnail(
        args.input,
        args.output,
        width, height,
        args.view,
        tuple(args.color) if args.color else None,
        tuple(args.background) if args.background else None,
        not args.no_transparent,
        not args.software_only
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
