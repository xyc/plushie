"""Builds the plush Clawd in Blender and renders its animation clips.

Run headless:
    blender -b --factory-startup -P blender/plush.py -- stills <dir> <scale> clip:frame ...
    blender -b --factory-startup -P blender/plush.py -- render build/layers [clip ...]

Every frame is rendered as two layers: Clawd alone on a clear background
(NNN.plush.png) and only the shadow it casts on the floor (NNN.shadow.png).
blender/composite.py lays one over the other into the frames the mod plays,
so the shadow's look can change without rendering again. `render` also
writes <dir>/manifest.json, listing every clip below.

Clawd is the pixel crab from Claude Code's banner: a wide body with two
eye notches, a stub arm on each side and four short legs. The plush keeps
that silhouette and adds what makes a toy read as soft: a pillowy body,
felt fuzz, bead eyes, and a rim light that makes the fuzz glow.
"""

import json
import math
import os
import sys
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

ORANGE = (0.69, 0.19, 0.095)  # linear #D97757, Claude's terracotta
FPS = 24

BODY_W, BODY_D, BODY_H = 1.40, 0.78, 0.82
LEG_H = 0.36
EYE_Z = BODY_H * 0.64
EYE_SCALE = (0.08, 0.05, 0.13)
# The frame fills a 16 x 6 cell box: about 256 x 192 device pixels in a
# Retina terminal, whose cells are roughly twice as tall as they are wide.
FRAME_W, FRAME_H = 256, 192
COLUMNS, ROWS = 16, 6

# Body size for the stuffing reaction: wider, much deeper, a little taller.
SIZES = {"normal": (1.0, 1.0, 1.0), "plump": (1.06, 1.18, 1.10), "stuffed": (1.12, 1.36, 1.20)}


@dataclass
class Clip:
    motion: str
    frames: int
    loop: bool
    prop: str | None = None
    size: str = "normal"


# Variants of one motion share its length, so the mod can swap between them
# mid-loop without a jump.
CLIPS = {
    "idle": Clip("idle", 48, True),
    "idle-plump": Clip("idle", 48, True, size="plump"),
    "idle-stuffed": Clip("idle", 48, True, size="stuffed"),
    "working": Clip("working", 24, True),
    "working-magnifier": Clip("working", 24, True, prop="magnifier"),
    "working-needles": Clip("working", 24, True, prop="needles"),
    "working-keyboard": Clip("working", 24, True, prop="keyboard"),
    "working-binoculars": Clip("working", 24, True, prop="binoculars"),
    "working-plump": Clip("working", 24, True, size="plump"),
    "working-stuffed": Clip("working", 24, True, size="stuffed"),
    "happy": Clip("happy", 32, False),
    "sleepy": Clip("sleepy", 64, True),
    "oops": Clip("oops", 36, False),
    "held": Clip("held", 24, True),
    "drop": Clip("drop", 16, False),
    "deflate": Clip("deflate", 24, False),
    "blush": Clip("blush", 32, False),
    "pat": Clip("pat", 28, False),
    "fidget-look": Clip("look", 36, False),
    "fidget-scratch": Clip("scratch", 32, False),
    "fidget-yawn": Clip("yawn", 40, False),
    "fidget-hop": Clip("hop", 20, False),
}


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for item in list(block):
            block.remove(item)


def felt_material(name="Felt", color=ORANGE, sheen_tint=(1.0, 0.62, 0.48)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = 0.92
    bsdf.inputs["Sheen Weight"].default_value = 0.8
    bsdf.inputs["Sheen Roughness"].default_value = 0.45
    bsdf.inputs["Sheen Tint"].default_value = (*sheen_tint, 1)
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


def plain_material(name, color, roughness=0.4, metallic=0.0, coat=0.0, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Coat Weight"].default_value = coat
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
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


def mesh_object(name, primitive, parent, location, scale=(1, 1, 1), rotation=(0, 0, 0), material=None, **kwargs):
    """A primitive placed under a parent; the props are built from these."""
    primitive(**kwargs)
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    obj.parent = parent
    obj.location = location
    obj.scale = scale
    obj.rotation_euler = rotation
    if material:
        obj.data.materials.append(material)
    return obj


def group(name, parent, location=(0, 0, 0), rotation=(0, 0, 0)):
    """An empty that a prop's pieces hang from, shown or hidden as one."""
    empty = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(empty)
    empty.parent = parent
    empty.location = location
    empty.rotation_euler = rotation
    return empty


def build_props(body, rig, hand):
    """The tool props: each an empty with its pieces, hidden until a clip asks."""
    brass = plain_material("Brass", (0.55, 0.36, 0.12), roughness=0.3, metallic=1.0)
    glass = plain_material("Glass", (0.70, 0.85, 1.0), roughness=0.05, coat=1.0)
    wood = plain_material("Wood", (0.30, 0.14, 0.06), roughness=0.6)
    yarn = felt_material("Yarn", (0.10, 0.32, 0.75), (0.7, 0.8, 1.0))
    needle = plain_material("Needle", (0.75, 0.75, 0.78), roughness=0.25, metallic=1.0)
    tip = plain_material("Tip", (0.95, 0.75, 0.15), roughness=0.4)
    plastic = plain_material("Plastic", (0.08, 0.08, 0.09), roughness=0.45)
    keycap = plain_material("Keycap", (0.85, 0.85, 0.82), roughness=0.5)
    ops = bpy.ops.mesh

    props = {}

    # A magnifying glass held out in front, its lens facing the camera.
    mag = group("Magnifier", hand, (0.05, -0.36, 0.14), (math.radians(80), 0, math.radians(-20)))
    mesh_object("MagRing", ops.primitive_torus_add, mag, (0, 0, 0), material=brass,
                major_radius=0.17, minor_radius=0.024)
    mesh_object("MagLens", ops.primitive_cylinder_add, mag, (0, 0, 0), material=glass,
                radius=0.155, depth=0.012)
    mesh_object("MagHandle", ops.primitive_cylinder_add, mag, (0, -0.28, 0), material=wood,
                rotation=(math.radians(90), 0, 0), radius=0.03, depth=0.24)
    props["magnifier"] = mag

    # Knitting: two crossed needles over a ball of yarn.
    knit = group("Needles", hand, (0.12, -0.34, 0.02))
    knit.scale = (1.5, 1.5, 1.5)
    mesh_object("Yarn", ops.primitive_uv_sphere_add, knit, (0, 0, -0.02), material=yarn,
                radius=0.08, segments=24, ring_count=12)
    for i, angle in enumerate((35, -35)):
        n = mesh_object(f"Needle{i}", ops.primitive_cylinder_add, knit, (0, -0.02, 0.06), material=needle,
                        rotation=(0, math.radians(angle), 0), radius=0.008, depth=0.34)
        mesh_object(f"NeedleTip{i}", ops.primitive_uv_sphere_add, n, (0, 0, 0.17), material=tip,
                    radius=0.018, segments=12, ring_count=6)
    props["needles"] = knit

    # A tiny keyboard sitting in front of the body, under the flapping arms.
    # Big enough to read at 16x6 cells, tilted up toward the camera so the keys show.
    keys = group("Keyboard", rig, (0.05, -BODY_D / 2 - 0.33, LEG_H + 0.04), (math.radians(34), 0, 0))
    keys.scale = (1.95, 1.95, 1.95)
    mesh_object("KeyBase", ops.primitive_cube_add, keys, (0, 0, 0), scale=(0.42, 0.16, 0.035),
                material=plastic, size=1)
    for row in range(3):
        for col in range(7):
            mesh_object(f"Key{row}{col}", ops.primitive_cube_add, keys,
                        (-0.165 + col * 0.055, -0.045 + row * 0.045, 0.025), scale=(0.042, 0.034, 0.02),
                        material=keycap, size=1)
    props["keyboard"] = keys

    # Binoculars held up in front of the eyes.
    barrel = plain_material("Barrel", (0.20, 0.21, 0.24), roughness=0.5)
    lens = plain_material("Lens", (0.04, 0.08, 0.16), roughness=0.1, coat=1.0)
    bino = group("Binoculars", body, (0, -BODY_D / 2 - 0.20, EYE_Z))
    for side in (-1, 1):
        mesh_object(f"Barrel{side}", ops.primitive_cylinder_add, bino, (side * 0.30, 0, 0), material=barrel,
                    rotation=(math.radians(90), 0, 0), radius=0.095, depth=0.28)
        mesh_object(f"Grip{side}", ops.primitive_torus_add, bino, (side * 0.30, -0.13, 0), material=plastic,
                    rotation=(math.radians(90), 0, 0), major_radius=0.095, minor_radius=0.018)
        mesh_object(f"Lens{side}", ops.primitive_cylinder_add, bino, (side * 0.30, -0.142, 0), material=lens,
                    rotation=(math.radians(90), 0, 0), radius=0.08, depth=0.01)
    mesh_object("Bridge", ops.primitive_cube_add, bino, (0, 0.02, 0), scale=(0.42, 0.08, 0.07),
                material=brass, size=1)
    props["binoculars"] = bino

    return props


def teardrop(name, parent, location, material):
    """A sweat drop: a sphere whose top half is drawn up into a point."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
    drop = bpy.context.active_object
    drop.name = name
    for v in drop.data.vertices:
        if v.co.z > 0:
            pinch = 1 - 0.85 * v.co.z
            v.co.x *= pinch
            v.co.y *= pinch
            v.co.z *= 1.7
    bpy.ops.object.shade_smooth()
    drop.data.materials.append(material)
    drop.parent = parent
    drop.location = location
    return drop


def heart(name, parent, location, material):
    """A heart from two lobes and a point, turned to face the camera."""
    root = group(name, parent, location, (0, 0, math.radians(18)))
    for side in (-1, 1):
        mesh_object(f"{name}Lobe{side}", bpy.ops.mesh.primitive_uv_sphere_add, root, (side * 0.5, 0, 0.25),
                    material=material, radius=0.6, segments=20, ring_count=10)
    mesh_object(f"{name}Point", bpy.ops.mesh.primitive_cone_add, root, (0, 0, -0.45), material=material,
                rotation=(math.radians(180), 0, 0), scale=(1.0, 0.55, 1.0), radius1=0.98, depth=1.1, vertices=24)
    return root


def show(obj, visible):
    for o in [obj, *obj.children_recursive]:
        o.hide_render = not visible


def build():
    clear_scene()
    felt = felt_material()
    bead = plain_material("Bead", (0.012, 0.010, 0.010), roughness=0.12, coat=1.0)

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
        # Swing forward (z) first, then raise (y): raising an arm already
        # swung forward lifts it in front of the body.
        pivot.rotation_mode = "ZYX"
        arm = soft_box(f"Arm{'L' if side < 0 else 'R'}", (0.34, 0.26, 0.20), 0.08,
                       (side * 0.17, 0, 0), pivot)
        arm.data.materials.append(felt)
        add_fuzz(arm, 2400, 0.045)
        arms.append(pivot)

    legs = []
    for i, x in enumerate((-0.52, -0.30, 0.30, 0.52)):
        # Hip pivot at the top of the leg, so a dangle swings from the body.
        hip = bpy.data.objects.new(f"Hip{i}", None)
        bpy.context.scene.collection.objects.link(hip)
        hip.parent = rig
        hip.location = (x, 0, LEG_H)
        leg = soft_box(f"Leg{i}", (0.13, 0.15, LEG_H + 0.08), 0.05, (0, 0, -(LEG_H + 0.08) / 2 + 0.06), hip)
        leg.data.materials.append(felt)
        add_fuzz(leg, 900, 0.018)
        legs.append(hip)

    eyes = []
    for side in (-1, 1):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
        eye = bpy.context.active_object
        eye.name = f"Eye{'L' if side < 0 else 'R'}"
        bpy.ops.object.shade_smooth()
        eye.data.materials.append(bead)
        eye.parent = body
        eye.location = (side * 0.30, -BODY_D / 2 - 0.06, EYE_Z)
        eye.scale = EYE_SCALE
        eyes.append(eye)

    # Blush: soft pink felt discs on the cheeks, below and outside the eyes.
    pink = felt_material("Blush", (0.95, 0.22, 0.32), (1.0, 0.7, 0.75))
    cheeks = []
    for side in (-1, 1):
        cheek = mesh_object(f"Cheek{'L' if side < 0 else 'R'}", bpy.ops.mesh.primitive_uv_sphere_add, body,
                            (side * 0.47, -BODY_D / 2 - 0.05, BODY_H * 0.44), material=pink,
                            radius=1, segments=24, ring_count=12)
        cheeks.append(cheek)

    sweat = teardrop("Sweat", body, (0.74, -BODY_D / 2 + 0.05, BODY_H + 0.08),
                     plain_material("Water", (0.35, 0.62, 1.0), roughness=0.05, coat=1.0, emission=0.15))

    props = build_props(body, rig, arms[1])

    love = plain_material("Heart", (0.95, 0.12, 0.25), roughness=0.25, coat=1.0, emission=0.5)
    hearts = [heart(f"Heart{i}", rig, (x, -0.1, 0), love) for i, x in enumerate((-0.35, 0.1, 0.45))]

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

    return {"rig": rig, "body": body, "arms": arms, "legs": legs, "eyes": eyes,
            "cheeks": cheeks, "sweat": sweat, "props": props, "hearts": hearts,
            "floor": floor, "toy": list(plush.objects)}


# Samples per layer: the shadow is a soft blur and needs far fewer.
LAYERS = {"plush": 48, "shadow": 24}


def set_layer(parts, layer):
    """Clawd alone (no floor), or the floor's shadow alone: Clawd hidden from
    the camera but still blocking the light, so the shadow is all that shows."""
    parts["floor"].hide_render = layer != "shadow"
    for obj in parts["toy"]:
        obj.visible_camera = layer == "plush"
    bpy.context.scene.cycles.samples = LAYERS[layer]


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
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, x):
    return a + (b - a) * x


@dataclass
class Pose:
    """Every channel a motion sets; the defaults are Clawd standing still."""
    hop: float = 0.0
    yaw: float = 0.0  # turn around the vertical axis
    roll: float = 0.0  # tip sideways
    lean: float = 0.0  # forward (+) or back (-)
    squash: float = 1.0
    arm_l: float = 0.0  # raise (+) or lower (-), radians
    arm_r: float = 0.0
    # Swing forward, toward the camera (+), so a raised arm shows in front of
    # the body instead of folding flat against its side.
    reach_l: float = 0.0
    reach_r: float = 0.0
    # Shoulder moved out from the body and up, per side: a stub arm raised from
    # where it hangs stays inside the body's outline, one raised from here
    # shows. Zero for every clip baked before the fidgets.
    shoulder_l: float = 0.0
    shoulder_r: float = 0.0
    legs: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    eye_z: float = 1.0  # eye height factor: 0.1 shut, 1 open, >1 wide
    cheeks: float = 0.0  # blush size, 0 hidden
    sweat: float = 0.0  # sweat drop size, 0 hidden
    sweat_slide: float = 0.0
    grow: float = 0.0  # 0 at the clip's size, 1 at stuffed (deflate)
    hearts: float = -1.0  # progress of the rising hearts, -1 none
    eye_x: float = 0.0  # eyes slide sideways to look left (-) or right (+)


def motion(name, t, frame, n):
    """One frame of a motion, t in [0, 1) across the clip."""
    p = Pose()
    if name == "idle":
        p.squash = 1 + 0.018 * math.sin(2 * math.pi * t)
        p.yaw = math.radians(4) * math.sin(2 * math.pi * t)
        p.arm_l = p.arm_r = math.radians(4) * math.sin(2 * math.pi * t)
        p.eye_z = {30: 0.55, 31: 0.12, 32: 0.12, 33: 0.55}.get(frame, 1.0)
    elif name == "working":
        s = math.sin(2 * math.pi * t)
        p.hop = 0.045 * abs(s)
        p.squash = 1 - 0.05 * (1 - abs(s))
        p.lean = math.radians(7)
        p.arm_l = math.radians(28) * math.sin(4 * math.pi * t)
        p.arm_r = -p.arm_l
    elif name == "happy":
        if t < 0.2:
            p.squash = 1 - 0.16 * ease(t / 0.2)
        elif t < 0.65:
            u = (t - 0.2) / 0.45
            p.hop = 0.26 * math.sin(math.pi * u)
            p.squash = 1.12 - 0.12 * u
            p.arm_l = p.arm_r = math.radians(70) * math.sin(math.pi * u)
        elif t < 0.82:
            p.squash = 1 - 0.12 * math.sin(math.pi * (t - 0.65) / 0.17)
        else:
            p.squash = 1 + 0.03 * math.sin(math.pi * (t - 0.82) / 0.18)
        p.eye_z = 0.55 if 0.2 <= t < 0.82 else 1.0
    elif name == "sleepy":
        p.squash = 1 + 0.035 * math.sin(2 * math.pi * t)
        p.roll = math.radians(7)
        p.arm_l = p.arm_r = math.radians(-10)
        p.eye_z = 0.13
    elif name == "oops":
        # Startle, wince, wobble, settle: a tip sideways reads where a twist
        # around the vertical axis doesn't, and the sweat drop says "oops".
        if t < 0.17:
            u = ease(t / 0.17)
            p.hop = 0.08 * math.sin(math.pi * u)
            p.squash = lerp(1.0, 1.1, u)
            p.arm_l = p.arm_r = math.radians(60) * u
            p.eye_z = lerp(1.0, 1.3, u)
        elif t < 0.33:
            u = ease((t - 0.17) / 0.16)
            p.squash = lerp(1.1, 0.8, u)
            p.arm_l = p.arm_r = lerp(math.radians(60), math.radians(-5), u)
            p.eye_z = lerp(1.3, 0.12, u)
        elif t < 0.8:
            u = (t - 0.33) / 0.47
            p.roll = math.radians(18) * (1 - u) * math.sin(5 * math.pi * u)
            p.squash = lerp(0.88, 1.0, ease(u))
            p.arm_l = p.arm_r = math.radians(-5)
            p.eye_z = lerp(0.6, 1.15, ease(u * 2))
            p.sweat = ease(u * 4)
            p.sweat_slide = 0.08 * u
        else:
            u = (t - 0.8) / 0.2
            p.squash = 1 - 0.04 * math.sin(math.pi * u)
            p.eye_z = lerp(0.75, 1.0, ease(u))
            p.sweat = 1 - ease(u)
            p.sweat_slide = 0.08
    elif name == "held":
        # Lifted off the floor and dangling: legs kick, the body swings.
        p.hop = 0.22
        p.squash = 1.07
        p.roll = math.radians(6) * math.sin(2 * math.pi * t)
        p.arm_l = math.radians(35) + math.radians(10) * math.sin(4 * math.pi * t)
        p.arm_r = math.radians(35) - math.radians(10) * math.sin(4 * math.pi * t)
        p.legs = [math.radians(12) * math.sin(4 * math.pi * t + i * math.pi / 2) for i in range(4)]
    elif name == "drop":
        if t < 0.3:
            u = t / 0.3
            p.hop = 0.22 * (1 - u * u)
            p.squash = lerp(1.07, 1.0, u)
            p.arm_l = p.arm_r = lerp(math.radians(35), math.radians(50), u)
        elif t < 0.55:
            u = (t - 0.3) / 0.25
            p.squash = 1 - 0.2 * math.sin(math.pi * u)
            p.arm_l = p.arm_r = lerp(math.radians(50), math.radians(-5), ease(u))
            p.eye_z = lerp(1.0, 0.4, math.sin(math.pi * u))
        else:
            u = (t - 0.55) / 0.45
            p.hop = 0.03 * math.sin(math.pi * u)
            p.squash = 1 + 0.05 * math.sin(math.pi * u) * (1 - u)
    elif name == "deflate":
        # From stuffed back to normal with a big sigh: a breath in, then out.
        if t < 0.25:
            u = ease(t / 0.25)
            p.grow = 1.0
            p.squash = lerp(1.0, 1.05, u)
            p.eye_z = lerp(1.0, 0.8, u)
        elif t < 0.8:
            u = ease((t - 0.25) / 0.55)
            p.grow = 1 - u
            p.squash = lerp(1.05, 0.9, u)
            p.eye_z = 0.13
            p.arm_l = p.arm_r = math.radians(-12) * u
        else:
            u = ease((t - 0.8) / 0.2)
            p.squash = lerp(0.9, 1.0, u)
            p.eye_z = lerp(0.13, 1.0, u)
            p.arm_l = p.arm_r = lerp(math.radians(-12), 0, u)
    elif name == "blush":
        p.cheeks = ease(t / 0.2) if t < 0.2 else (1 - ease((t - 0.85) / 0.15) if t > 0.85 else 1.0)
        p.yaw = math.radians(6) * math.sin(4 * math.pi * t) * p.cheeks
        p.roll = math.radians(5) * p.cheeks
        p.squash = 1 - 0.03 * p.cheeks
        p.arm_l = p.arm_r = math.radians(-8) * p.cheeks
        p.eye_z = lerp(1.0, 0.45, p.cheeks)
    elif name == "pat":
        # Squished by the pat, bounces back pleased; hearts float up.
        if t < 0.25:
            p.squash = lerp(1.0, 0.86, ease(t / 0.25))
        elif t < 0.55:
            u = (t - 0.25) / 0.3
            p.squash = lerp(0.86, 1.06, ease(u))
            p.hop = 0.04 * math.sin(math.pi * u)
        else:
            u = (t - 0.55) / 0.45
            p.squash = 1 + 0.06 * (1 - ease(u))
        p.yaw = math.radians(5) * math.sin(4 * math.pi * t) * (1 - t)
        p.arm_l = p.arm_r = math.radians(20) * math.sin(math.pi * t)
        p.eye_z = 0.45 if 0.1 < t < 0.9 else 1.0
        p.hearts = t
    elif name == "look":
        # Turn to look left, hold, across to the right, hold, back.
        keys = [(0.0, 0.0), (0.15, -1.0), (0.4, -1.0), (0.6, 1.0), (0.82, 1.0), (1.0, 0.0)]
        for (t0, a), (t1, b) in zip(keys, keys[1:]):
            if t0 <= t < t1:
                look = lerp(a, b, ease((t - t0) / (t1 - t0)))
                break
        else:
            look = 0.0
        p.yaw = math.radians(16) * look
        p.eye_x = 0.05 * look
        p.eye_z = {14: 0.5, 15: 0.15, 16: 0.5}.get(frame, 1.0)
    elif name == "scratch":
        # The right arm reaches up and scratches; the body leans into it.
        reach = ease(t / 0.2) if t < 0.2 else (1 - ease((t - 0.8) / 0.2) if t > 0.8 else 1.0)
        p.arm_r = math.radians(80) * reach + math.radians(14) * math.sin(10 * math.pi * t) * reach
        p.reach_r = math.radians(25) * reach
        p.shoulder_r = reach
        p.roll = math.radians(-6) * reach
        p.eye_z = lerp(1.0, 0.45, reach)
    elif name == "yawn":
        # Stretch tall with arms up and eyes shut, hold, then settle with a shiver.
        if t < 0.35:
            u = ease(t / 0.35)
            p.squash = lerp(1.0, 1.12, u)
            p.arm_l = p.arm_r = math.radians(60) * u
            p.reach_l = p.reach_r = math.radians(20) * u
            p.shoulder_l = p.shoulder_r = u
            p.eye_z = lerp(1.0, 0.12, u)
            p.lean = math.radians(-6) * u
        elif t < 0.65:
            p.squash = 1.12
            p.arm_l = p.arm_r = math.radians(60)
            p.reach_l = p.reach_r = math.radians(20)
            p.shoulder_l = p.shoulder_r = 1.0
            p.eye_z = 0.12
            p.lean = math.radians(-6)
        else:
            u = ease((t - 0.65) / 0.35)
            p.squash = lerp(1.12, 1.0, u) - 0.03 * math.sin(6 * math.pi * u) * (1 - u)
            p.arm_l = p.arm_r = lerp(math.radians(60), 0, u)
            p.reach_l = p.reach_r = lerp(math.radians(20), 0, u)
            p.shoulder_l = p.shoulder_r = 1 - u
            p.eye_z = lerp(0.12, 1.0, u)
            p.lean = lerp(math.radians(-6), 0, u)
    elif name == "hop":
        # Two little hops in place, a squash before each.
        u = (t * 2) % 1
        p.hop = 0.1 * math.sin(math.pi * min(1.0, max(0.0, (u - 0.2) / 0.8)))
        p.squash = 0.9 if u < 0.2 else 1.05 - 0.05 * u
        p.arm_l = p.arm_r = math.radians(25) * math.sin(math.pi * u)
    else:
        raise ValueError(f"unknown motion {name}")
    return p


def pose(parts, clip_name, frame):
    """Sets the rig for one frame of a clip: its motion, then its variant."""
    clip = CLIPS[clip_name]
    p = motion(clip.motion, frame / clip.frames, frame, clip.frames)
    rig, body, arms, eyes = parts["rig"], parts["body"], parts["arms"], parts["eyes"]

    # A held prop pins the hand: the right arm stays raised to show it.
    if clip.prop in ("magnifier", "needles"):
        p.arm_r = math.radians(18) + 0.25 * p.arm_r
    elif clip.prop == "binoculars":
        p.arm_l = p.arm_r = math.radians(40)
    for name, prop in parts["props"].items():
        show(prop, name == clip.prop)

    size = SIZES[clip.size]
    if p.grow:
        size = tuple(lerp(s, t, p.grow) for s, t in zip(size, SIZES["stuffed"]))

    rig.location = (0, 0, p.hop)
    rig.rotation_euler = (p.lean, p.roll, p.yaw)
    # Squash keeps volume: thinner and taller, or wider and shorter.
    side = 1 / math.sqrt(p.squash)
    body.scale = (side * size[0], side * size[1], p.squash * size[2])
    # Arms raise by rolling around the body's front-back axis, away from it.
    # A forward swing turns the arm around the vertical axis toward the front
    # (-y), opposite ways for the two sides.
    arms[0].rotation_euler = (0, p.arm_l, p.reach_l)
    arms[1].rotation_euler = (0, -p.arm_r, -p.reach_r)
    for pivot, side, out in ((arms[0], -1, p.shoulder_l), (arms[1], 1, p.shoulder_r)):
        pivot.location = (side * (BODY_W / 2 - 0.04 + 0.14 * out), 0, BODY_H * (0.40 + 0.16 * out))
    for hip, swing in zip(parts["legs"], p.legs):
        hip.rotation_euler = (swing, 0, 0)
    for eye in eyes:
        eye.scale = (EYE_SCALE[0], EYE_SCALE[1], EYE_SCALE[2] * p.eye_z)
        eye.location.z = EYE_Z
        eye.location.x = (0.30 if eye.name.endswith("R") else -0.30) + p.eye_x

    for cheek in parts["cheeks"]:
        cheek.scale = (0.11 * p.cheeks, 0.03 * p.cheeks, 0.075 * p.cheeks)
        cheek.hide_render = p.cheeks <= 0.01
    sweat = parts["sweat"]
    sweat.scale = (0.09 * p.sweat, 0.06 * p.sweat, 0.10 * p.sweat)
    sweat.location.z = BODY_H + 0.08 - p.sweat_slide
    sweat.hide_render = p.sweat <= 0.01

    # Each heart starts a little after the last, rises, swells, then shrinks away.
    top = LEG_H + BODY_H
    for i, h in enumerate(parts["hearts"]):
        u = (p.hearts - i * 0.15) / 0.65
        visible = p.hearts >= 0 and 0 < u < 1
        size = 0.085 * math.sin(math.pi * min(1.0, max(0.0, u))) if visible else 0.0
        h.location.z = top + 0.05 + 0.35 * max(0.0, u)
        h.scale = (size, size, size)
        show(h, visible and size > 0.005)


def write_manifest(out_dir):
    manifest = {
        "fps": FPS,
        "columns": COLUMNS,
        "rows": ROWS,
        "clips": {name: {"frames": c.frames, "loop": c.loop} for name, c in CLIPS.items()},
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def render_frame(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    command = args[0] if args else "preview"
    parts = build()

    if command == "stills":
        # stills <dir> <scale> clip:frame ...: single frames for a contact sheet.
        out_dir, scale = os.path.abspath(args[1]), int(args[2])
        setup_render(FRAME_W * scale, FRAME_H * scale)
        for layer in LAYERS:
            set_layer(parts, layer)
            for spec in args[3:]:
                clip, frame = spec.split(":")
                pose(parts, clip, int(frame))
                render_frame(os.path.join(out_dir, f"{clip}-{frame}.{layer}.png"))
    elif command == "render":
        out_dir = os.path.abspath(args[1])
        clips = args[2:] or list(CLIPS)
        write_manifest(out_dir)
        setup_render(FRAME_W, FRAME_H)
        # A layer at a time through each clip: switching layers changes what
        # the camera sees, which costs the kept render data a rebuild.
        for clip in clips:
            for layer in LAYERS:
                set_layer(parts, layer)
                for frame in range(CLIPS[clip].frames):
                    pose(parts, clip, frame)
                    render_frame(os.path.join(out_dir, clip, f"{frame:03d}.{layer}.png"))


main()
