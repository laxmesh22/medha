"""Convert a Microsoft Rocketbox avatar (MIT licence) FBX -> web GLB.

    blender -b --factory-startup -P tools/blender/rocketbox_to_glb.py -- <avatar_dir> <out.glb> [tex_size]

<avatar_dir> contains Export/<name>.fbx and Textures/*.tga (layout of github.com/microsoft/Microsoft-Rocketbox).
Textures are downscaled (default 1024) so the station loads fast; skinning is kept, animations dropped.
"""

import sys
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
avatar_dir, out_path = Path(argv[0]), Path(argv[1])
tex_size = int(argv[2]) if len(argv) > 2 else 1024

bpy.ops.wm.read_factory_settings(use_empty=True)
fbx = next((avatar_dir / "Export").glob("*.fbx"))
bpy.ops.import_scene.fbx(filepath=str(fbx), use_anim=False)
# The FBX references the original artist's paths (..\temp\Humans\...): remap by file name.
for img in bpy.data.images:
    local = (avatar_dir / "Textures" / Path(img.filepath.replace("\\", "/")).name).resolve()
    if local.exists():
        img.filepath = str(local)
        img.reload()
        img.pixels[0]  # force load so the size is known
    else:
        print("missing texture", local)

# Specular maps feed "Specular IOR Level": not needed on the web, drop to keep the GLB small.
for mat in bpy.data.materials:
    if mat.use_nodes:
        for link in list(mat.node_tree.links):
            if link.to_socket.name == "Specular IOR Level":
                mat.node_tree.links.remove(link)

for img in bpy.data.images:
    if img.size[0] > tex_size:
        img.scale(tex_size, tex_size)
    print("image", img.name, tuple(img.size), "alpha" if img.alpha_mode != "NONE" else "")

# Wire opacity textures (eyelashes, hair cards) into Alpha so glTF exports them as transparent.
for mat in bpy.data.materials:
    if not mat.use_nodes:
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    for n in nodes:
        if n.type == "TEX_IMAGE" and n.image and "opacity" in n.image.name.lower() and not bsdf.inputs["Alpha"].is_linked:
            links.new(n.outputs["Color"], bsdf.inputs["Alpha"])
            mat.surface_render_method = "BLENDED"
    print("material", mat.name, [n.image.name for n in nodes if n.type == "TEX_IMAGE" and n.image])

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
print("armature", arm.name, "bones:", [b.name for b in arm.data.bones if "Bip01" in b.name][:40])
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
zs = [(o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices]
print("height_m", round(max(zs) - min(zs), 3))

out_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(out_path), export_format="GLB", export_skins=True, export_animations=False,
    export_yup=True, export_image_format="AUTO", export_morph=False,
)
print("wrote", out_path, out_path.stat().st_size)
