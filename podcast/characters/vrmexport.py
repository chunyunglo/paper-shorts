"""Turn the built character into a VRM 1.0: T-pose rest, eye bones, humanoid map, expressions."""
import bpy
import numpy as np
from mathutils import Vector, Matrix


def _meshes(rig):
    return [o for o in bpy.data.objects if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers)]


def _eval_coords(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    co = np.array([v.co[:] for v in m.vertices])
    e.to_mesh_clear()
    return co


def bake_pose_as_rest(rig):
    """Deform every mesh (and each of its shape keys) by the current pose, then make the pose the rest pose."""
    for o in _meshes(rig):
        keys = o.data.shape_keys.key_blocks if o.data.shape_keys else []
        for k in keys:
            k.value = 0.0
        bpy.context.view_layer.update()
        base = _eval_coords(o)
        per = {}
        for k in keys[1:]:
            k.value = 1.0
            bpy.context.view_layer.update()
            per[k.name] = _eval_coords(o)
            k.value = 0.0
        o['_baked'] = True
        if keys:
            keys[0].data.foreach_set('co', base.ravel())
            for k in keys[1:]:
                k.data.foreach_set('co', per[k.name].ravel())
        o.data.vertices.foreach_set('co', base.ravel())
        o.data.update()
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def aim(rig, bone, direction):
    """Rotate a pose bone so its head->tail points along direction (world space), keeping roll as close as possible."""
    pb = rig.pose.bones[bone]
    bpy.context.view_layer.update()
    m = rig.matrix_world @ pb.matrix
    cur = (m.to_3x3() @ Vector((0, 1, 0))).normalized()
    q = cur.rotation_difference(Vector(direction).normalized())
    loc = m.translation.copy()
    new = (q.to_matrix().to_4x4() @ Matrix.Translation(-loc) @ m)
    new = Matrix.Translation(loc) @ new
    pb.matrix = rig.matrix_world.inverted() @ new
    bpy.context.view_layer.update()


def t_pose(rig):
    for side, sgn in (('l', 1), ('r', -1)):
        for b in ('upperarm', 'lowerarm', 'hand'):
            aim(rig, f'{b}_{side}', (sgn, 0, 0))
        for f in ('index', 'middle', 'ring', 'pinky'):
            for i in (1, 2, 3):
                aim(rig, f'{f}_0{i}_{side}', (sgn, 0, 0))
        for b in ('thigh', 'calf'):
            aim(rig, f'{b}_{side}', (0, 0, -1))


def add_eye_bones(rig, eyes):
    """Two eye bones under the head, and the eye mesh weighted fully to them (for look-at)."""
    co = np.array([eyes.matrix_world @ v.co for v in eyes.data.vertices])
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    eb = rig.data.edit_bones
    for side, sgn in (('l', 1), ('r', -1)):
        sel = co[:, 0] * sgn > 0
        c = co[sel].mean(0)
        b = eb.new(f'eye_{side}')
        b.head = Vector(c)
        b.tail = Vector(c) + Vector((0, -0.02, 0))
        b.parent = eb['head']
    bpy.ops.object.mode_set(mode='OBJECT')
    for vg in list(eyes.vertex_groups):
        eyes.vertex_groups.remove(vg)
    for side, sgn in (('l', 1), ('r', -1)):
        vg = eyes.vertex_groups.new(name=f'eye_{side}')
        vg.add([i for i in range(len(co)) if co[i, 0] * sgn > 0], 1.0, 'REPLACE')


HUMANOID = {
    'hips': 'pelvis', 'spine': 'spine_01', 'chest': 'spine_02', 'upperChest': 'spine_03', 'neck': 'neck_01', 'head': 'head',
    'leftEye': 'eye_l', 'rightEye': 'eye_r',
    'leftUpperLeg': 'thigh_l', 'leftLowerLeg': 'calf_l', 'leftFoot': 'foot_l', 'leftToes': 'ball_l',
    'rightUpperLeg': 'thigh_r', 'rightLowerLeg': 'calf_r', 'rightFoot': 'foot_r', 'rightToes': 'ball_r',
    'leftShoulder': 'clavicle_l', 'leftUpperArm': 'upperarm_l', 'leftLowerArm': 'lowerarm_l', 'leftHand': 'hand_l',
    'rightShoulder': 'clavicle_r', 'rightUpperArm': 'upperarm_r', 'rightLowerArm': 'lowerarm_r', 'rightHand': 'hand_r',
}
for side, S in (('l', 'left'), ('r', 'right')):
    for f, F in (('thumb', 'Thumb'), ('index', 'Index'), ('middle', 'Middle'), ('ring', 'Ring'), ('pinky', 'Little')):
        names = ('Metacarpal', 'Proximal', 'Distal') if f == 'thumb' else ('Proximal', 'Intermediate', 'Distal')
        for i, nm in enumerate(names, 1):
            HUMANOID[f'{S}{F}{nm}'] = f'{f}_0{i}_{side}'


def setup_vrm(rig, body, meta):
    from bl_ext.user_default.vrm.editor.extension_accessor import get_armature_extension
    ext = get_armature_extension(rig.data)
    ext.spec_version = '1.0'
    v1 = ext.vrm1
    m = v1.meta
    m.vrm_name = meta['name']
    if not len(m.authors):
        m.authors.add()
    m.authors[0].value = meta.get('author', 'paper-shorts')
    m.license_url = 'https://vrm.dev/licenses/1.0/'
    m.avatar_permission = 'everyone'
    m.commercial_usage = 'corporation'
    m.allow_redistribution = True
    m.modification = 'allowModificationRedistribution'
    hb = v1.humanoid.human_bones
    for hname, bname in HUMANOID.items():
        getattr(hb, _snake(hname)).node.bone_name = bname
    ex = v1.expressions.preset
    keys = [k.name for k in body.data.shape_keys.key_blocks]
    for name in ('aa', 'ih', 'ou', 'ee', 'oh', 'blink', 'happy', 'relaxed', 'surprised', 'sad', 'angry'):
        if name not in keys:
            continue
        e = getattr(ex, name)
        bind = e.morph_target_binds.add()
        bind.node.mesh_object_name = body.name
        bind.index = name
        bind.weight = 1.0
    for name, attr in (('blinkLeft', 'blink_left'), ('blinkRight', 'blink_right')):
        if name in keys:
            e = getattr(ex, attr)
            bind = e.morph_target_binds.add()
            bind.node.mesh_object_name = body.name
            bind.index = name
    la = v1.look_at
    la.type = 'bone'
    la.offset_from_head_bone = (0.0, 0.06, -0.03)


def _snake(s):
    out = ''
    for ch in s:
        out += ('_' + ch.lower()) if ch.isupper() else ch
    return out


def export(path):
    r = bpy.ops.export_scene.vrm(filepath=path, export_invisibles=False, export_only_selections=False,
                                 enable_advanced_preferences=False)
    return r
