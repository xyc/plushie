"""Builds the plush Clawd in Blender and renders its mood animations.

Run headless:
    blender -b --factory-startup -P blender/plush.py -- preview out.png [mood] [frame] [size]
    blender -b --factory-startup -P blender/plush.py -- render assets/frames [mood ...]

Clawd is the pixel crab from Claude Code's banner: a wide body with two
eye notches, a stub arm on each side and four short legs. The plush keeps
that silhouette and adds what makes a toy read as soft: a pillowy body,
felt fuzz, bead eyes, and a rim light that makes the fuzz glow.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

ORANGE = (0.69, 0.19, 0.095)  # linear #D97757, Claude's terracotta
FPS = 24

BODY_W, BODY_D, BODY_H = 1.40, 0.78, 0.82
LEG_H = 0.36
# The frame fills a 16 x 6 cell box: about 256 x 192 device pixels in a
# Retina terminal, whose cells are roughly twice as tall as they are wide.
FRAME_W, FRAME_H = 256, 192

# Frames per mood, and whether it loops or plays once and hands back to idle.
MOODS = {
    "idle": (48, True),
    "working": (24, True),
    "happy": (32, False),
    "sleepy": (64, True),
    "oops": (20, False),
}


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for item in list(block):
            block.remove(item)


def felt_material():
    mat = bpy.data.materials.new("Felt")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*ORANGE, 1)
    bsdf.inputs["Roughness"].default_value = 0.92
    bsdf.inputs["Sheen Weight"].default_value = 0.8
    bsdf.inputs["Sheen Roughness"].default_value = 0.45
    bsdf.inputs["Sheen Tint"].default_value = (1.0, 0.62, 0.48, 1)
    bsdf.inputs["Subsurface Weight"].default_value = 0.15
    bsdf.inputs["Subsurface Radius"].default_value = (0.05, 0.02, 0.01)

    # Fine fibre noise as a bump, so the surface reads as felt up close.
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180.0
    noise.inputs["Detail"].default_value = 8.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.004
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def bead_material():
    mat = bpy.data.materials.new("Bead")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.012, 0.010, 0.010, 1)
    bsdf.inputs["Roughness"].default_value = 0.12
    bsdf.inputs["Coat Weight"].default_value = 1.0
    return mat


def soft_box(name, size, bevel, location, parent=None):
    """A rounded box: bevel then subdivision, the shape of a stuffed panel."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name
    # Bake the size into the mesh so object scale stays free for animation.
    for v in obj.data.vertices:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width = bevel
    mod.segments = 3
    sub = obj.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 3
    bpy.ops.object.shade_smooth()
    if parent:
        obj.parent = parent
    obj.location = location
    return obj


def add_fuzz(obj, count, length, material_index=0):
    mod = obj.modifiers.new("Fuzz", "PARTICLE_SYSTEM")
    ps = mod.particle_system.settings
    ps.type = "HAIR"
    ps.count = count
    ps.use_modifier_stack = True
    ps.emit_from = "FACE"
    ps.use_even_distribution = True
    ps.material = material_index + 1
    ps.child_type = "INTERPOLATED"
    ps.child_percent = 6
    ps.rendered_child_count = 12
    ps.child_length = 1.0
    ps.roughness_1 = 0.008
    ps.roughness_1_size = 1.0
    ps.roughness_endpoint = 0.014
    ps.roughness_end_shape = 1.0
    ps.clump_factor = 0.0
    ps.root_radius = 0.0011
    ps.tip_radius = 0.0
    ps.radius_scale = 1.0
    ps.display_step = 3
    ps.render_step = 2  # 4 segments: plenty for fuzz this short
    # hair_length is derived from the emission velocity (it rescales
    # normal_factor), so it is set last; the random velocity is absolute and
    # tilts each fibre a little off the normal.
    ps.factor_random = length * 0.5
    ps.hair_length = length
    return mod


def build():
    clear_scene()
    felt, bead = felt_material(), bead_material()

    rig = bpy.data.objects.new("Rig", None)
    bpy.context.scene.collection.objects.link(rig)

    # The body's origin sits at its bottom, so squash keeps the feet planted.
    body = soft_box("Body", (BODY_W, BODY_D, BODY_H), 0.24, (0, 0, LEG_H), rig)
    for v in body.data.vertices:
        v.co.z += BODY_H / 2
    body.data.materials.append(felt)
    add_fuzz(body, 24000, 0.055)

    arms = []
    for side in (-1, 1):
        # Shoulder pivot at the body's side; the arm hangs outward from it.
        pivot = bpy.data.objects.new(f"Shoulder{'L' if side < 0 else 'R'}", None)
        bpy.context.scene.collection.objects.link(pivot)
        pivot.parent = body
        pivot.location = (side * (BODY_W / 2 - 0.04), 0, BODY_H * 0.40)
        arm = soft_box(f"Arm{'L' if side < 0 else 'R'}", (0.34, 0.26, 0.20), 0.08,
                       (side * 0.17, 0, 0), pivot)
        arm.data.materials.append(felt)
        add_fuzz(arm, 2400, 0.045)
        arms.append(pivot)

    for i, x in enumerate((-0.52, -0.30, 0.30, 0.52)):
        leg = soft_box(f"Leg{i}", (0.13, 0.15, LEG_H + 0.08), 0.05, (x, 0, (LEG_H + 0.08) / 2 - 0.02), rig)
        leg.data.materials.append(felt)
        add_fuzz(leg, 900, 0.018)

    eyes = []
    for side in (-1, 1):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
        eye = bpy.context.active_object
        eye.name = f"Eye{'L' if side < 0 else 'R'}"
        bpy.ops.object.shade_smooth()
        eye.data.materials.append(bead)
        eye.parent = body
        eye.location = (side * 0.30, -BODY_D / 2 - 0.06, BODY_H * 0.64)
        eye.scale = (0.08, 0.05, 0.13)
        eyes.append(eye)

    # The floor keeps only the shadow, in the alpha, so it sits on any terminal
    # colour. Only the overhead light below reaches it: a shadow from the side
    # trails off as a dark smear on a dark terminal, one from above pools
    # under the feet.
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.is_shadow_catcher = True

    plush = bpy.data.collections.new("Plush")
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj is not floor:
            plush.objects.link(obj)
    ground = bpy.data.collections.new("Ground")
    ground.objects.link(floor)

    target = bpy.data.objects.new("Target", None)
    bpy.context.scene.collection.objects.link(target)
    target.location = (0, 0, LEG_H + BODY_H * 0.56)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 88
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (1.9, -5.4, 2.1)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    bpy.context.scene.camera = cam

    def area(name, loc, energy, size, receivers, color=(1, 1, 1)):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.size, light.color = energy, size, color
        obj = bpy.data.objects.new(name, light)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = loc
        c = obj.constraints.new("TRACK_TO")
        c.target = target
        obj.light_linking.receiver_collection = receivers
        return obj

    area("Key", (-2.6, -3.4, 3.4), 520, 3.0, plush, (1.0, 0.96, 0.9))
    area("Fill", (3.4, -2.2, 1.4), 220, 5.0, plush, (0.9, 0.94, 1.0))
    # The rim sits behind and above: it lights the fuzz along the silhouette.
    area("Rim", (0.8, 3.2, 2.8), 1000, 2.0, plush, (1.0, 0.9, 0.82))
    # Big and close, so the shadow is all soft edge: a grey pool, not a slab.
    area("Shadow", (0, 0, 2.6), 300, 5.0, ground)

    # No sky light: the world would reach the floor from every side, and the
    # toy blocking it darkens a wide band. The fill does its job instead.
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    bpy.context.scene.world = world

    return {"rig": rig, "body": body, "arms": arms, "eyes": eyes}


def setup_render(width, height):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type != "CPU"
    scene.cycles.device = "GPU"
    scene.cycles.samples = 48
    # Frames differ only in object transforms, so the hair's geometry can be
    # kept between renders instead of rebuilt every frame.
    scene.render.use_persistent_data = True
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 90
    scene.view_settings.view_transform = "Standard"


def ease(x):
    return x * x * (3 - 2 * x)


def pose(parts, mood, frame):
    """Sets the rig for one frame of a mood; every value is a function of time."""
    n, _ = MOODS[mood]
    t = frame / n
    rig, body, arms, eyes = parts["rig"], parts["body"], parts["arms"], parts["eyes"]

    hop, sway, tilt, lean = 0.0, 0.0, 0.0, 0.0
    squash = 1.0
    arm_l = arm_r = 0.0
    eye_z = 1.0

    if mood == "idle":
        squash = 1 + 0.018 * math.sin(2 * math.pi * t)
        sway = math.radians(4) * math.sin(2 * math.pi * t)
        arm_l = arm_r = math.radians(4) * math.sin(2 * math.pi * t)
        blink = {30: 0.55, 31: 0.12, 32: 0.12, 33: 0.55}
        eye_z = blink.get(frame, 1.0)
    elif mood == "working":
        s = math.sin(2 * math.pi * t)
        hop = 0.045 * abs(s)
        squash = 1 - 0.05 * (1 - abs(s))
        lean = math.radians(7)
        arm_l = math.radians(28) * math.sin(4 * math.pi * t)
        arm_r = -arm_l
    elif mood == "happy":
        if t < 0.2:
            squash = 1 - 0.16 * ease(t / 0.2)
        elif t < 0.65:
            u = (t - 0.2) / 0.45
            hop = 0.26 * math.sin(math.pi * u)
            squash = 1.12 - 0.12 * u
            arm_l = arm_r = math.radians(70) * math.sin(math.pi * u)
        elif t < 0.82:
            u = (t - 0.65) / 0.17
            squash = 1 - 0.12 * math.sin(math.pi * u)
        else:
            u = (t - 0.82) / 0.18
            squash = 1 + 0.03 * math.sin(math.pi * u)
        eye_z = 0.55 if 0.2 <= t < 0.82 else 1.0
    elif mood == "sleepy":
        squash = 1 + 0.035 * math.sin(2 * math.pi * t)
        tilt = math.radians(7)
        arm_l = arm_r = math.radians(-10)
        eye_z = 0.13
    elif mood == "oops":
        decay = 1 - t
        sway = math.radians(14) * decay * math.sin(6 * math.pi * t)
        squash = 1 - 0.08 * decay
        eye_z = 1.25

    rig.location = (0, 0, hop)
    rig.rotation_euler = (lean, tilt, sway)
    # Squash keeps volume: thinner and taller, or wider and shorter.
    side = 1 / math.sqrt(squash)
    body.scale = (side, side, squash)
    # Arms raise by rolling around the body's front-back axis, away from it.
    arms[0].rotation_euler = (0, arm_l, 0)
    arms[1].rotation_euler = (0, -arm_r, 0)
    for eye in eyes:
        eye.scale.z = 0.13 * eye_z


def render_frame(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    command = args[0] if args else "preview"
    parts = build()

    if command == "preview":
        out = os.path.abspath(args[1] if len(args) > 1 else "preview.png")
        mood = args[2] if len(args) > 2 else "idle"
        frame = int(args[3]) if len(args) > 3 else 0
        scale = int(args[4]) if len(args) > 4 else 2
        setup_render(FRAME_W * scale, FRAME_H * scale)
        pose(parts, mood, frame)
        render_frame(out)
    elif command == "stills":
        # stills <dir> <scale> mood:frame ...: single frames for a contact sheet.
        out_dir, scale = os.path.abspath(args[1]), int(args[2])
        setup_render(FRAME_W * scale, FRAME_H * scale)
        for spec in args[3:]:
            mood, frame = spec.split(":")
            pose(parts, mood, int(frame))
            render_frame(os.path.join(out_dir, f"{mood}-{frame}.png"))
    elif command == "render":
        out_dir = os.path.abspath(args[1])
        moods = args[2:] or list(MOODS)
        setup_render(FRAME_W, FRAME_H)
        for mood in moods:
            n, _ = MOODS[mood]
            for frame in range(n):
                pose(parts, mood, frame)
                render_frame(os.path.join(out_dir, mood, f"{frame:03d}.png"))


main()
