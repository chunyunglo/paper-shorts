"""Quick Cycles CPU preview renders of a built character (.blend): face and full body.
Usage: python preview.py char.blend out_prefix [shape_key ...]"""
import sys, math, bpy
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath=sys.argv[1])
out = sys.argv[2]
keys = [a for a in sys.argv[3:] if not a.startswith('--')]
body = bpy.data.objects.get('Body')
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.samples = 24; sc.cycles.use_denoising = True
sc.cycles.device = 'CPU'
sc.render.resolution_x = 640; sc.render.resolution_y = 800
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.07, 1); w.node_tree.nodes['Background'].inputs[1].default_value = 1
def light(name, loc, energy, size=1.0):
    d = bpy.data.lights.new(name, 'AREA'); d.energy = energy; d.size = size
    o = bpy.data.objects.new(name, d); sc.collection.objects.link(o); o.location = loc
    o.rotation_euler = (Vector((0, 0, 1.5)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
light('key', (-1.2, -2.2, 2.2), 300, 1.5); light('fill', (1.5, -1.8, 1.6), 120, 2); light('rim', (0.8, 1.8, 2.2), 200, 1)
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
def shoot(name, target, dist, lens):
    cam.data.lens = lens
    cam.location = Vector(target) + Vector((0.25 * dist, -dist, 0.05))
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.render.filepath = f"{out}_{name}.png"; bpy.ops.render.render(write_still=True)
COL = {'Body': (0.8, 0.6, 0.5), 'Shirt': (0.92, 0.92, 0.95), 'Collar': (0.95, 0.95, 0.97), 'Jacket': (0.05, 0.07, 0.15),
       'Lapels': (0.03, 0.04, 0.1), 'Trousers': (0.05, 0.07, 0.15), 'Belt': (0.05, 0.03, 0.02), 'Shoes': (0.02, 0.02, 0.02),
       'Tie': (0.5, 0.05, 0.08), 'Eyes': (0.9, 0.9, 0.9), 'Hair': (0.05, 0.03, 0.02)}
for o in bpy.data.objects:
    if o.type == 'MESH' and (not o.data.materials or o.data.materials[0] is None or not o.data.materials[0].use_nodes or '--keep' not in sys.argv):
        if o.name in COL and not (o.data.materials and o.data.materials[0] and o.data.materials[0].get('custom')):
            m = bpy.data.materials.new(o.name + '_pv'); m.use_nodes = True
            m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*COL[o.name], 1)
            o.data.materials.clear(); o.data.materials.append(m)
import numpy as _np
_bb = _np.array([body.matrix_world @ Vector(c) for c in body.bound_box]); H = _bb[:, 2].max()
if body.data.shape_keys:
    for k in body.data.shape_keys.key_blocks[1:]:
        k.value = 0
    for k in keys:
        n, _, v = k.partition('=')
        body.data.shape_keys.key_blocks[n].value = float(v or 1)
shoot('face', (0, 0, H * 0.9), 1.0, 70)
shoot('full', (0, 0, H * 0.52), 3.6, 50)
if '--side' in sys.argv:
    cam.data.lens = 70; cam.location = Vector((1.0, -0.15, H * 0.9)); cam.rotation_euler = (Vector((0, 0, H * 0.9)) - cam.location).to_track_quat('-Z', 'Y').to_euler(); sc.render.filepath = f'{out}_side.png'; bpy.ops.render.render(write_still=True)
if '--torso' in sys.argv: shoot('torso', (0, 0, H * 0.78), 1.6, 50)
