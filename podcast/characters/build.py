"""Build a talk-show host from scratch in Blender (bpy module, headless) and export it as VRM 1.0.

Body: MakeHuman base mesh and targets through MPFB2 (CC0 assets, GPL code).
Clothes, hair, skin texture and facial expressions are generated here.

Usage: python build.py <character.json> <out.vrm>
"""
import sys, os, json, math, importlib
from pathlib import Path
import bpy, bmesh, addon_utils
import numpy as np
from mathutils import Vector

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
CACHE = Path(__file__).resolve().parent.parent / '.cache'
MPFB = Path(os.environ.get('MPFB_SRC', CACHE / 'mpfb2/src/mpfb'))
MH = Path(os.environ.get('MH_DATA', CACHE / 'makehuman/makehuman/data'))
UNITS = MPFB / 'data' / 'targets' / 'expression' / 'units'


def boot():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for ext in ('mpfb', 'vrm'):
        addon_utils.enable(f"bl_ext.user_default.{ext}", default_set=True, persistent=True)
    return lambda mod, k: getattr(importlib.import_module("bl_ext.user_default.mpfb." + mod), k)


get = boot()
HumanService = get("services.humanservice", "HumanService")
TargetService = get("services.targetservice", "TargetService")
HumanObjectProperties = get("entities.objectproperties", "HumanObjectProperties")


def target_path(name):
    p = TargetService.target_full_path(name)
    if not p:
        raise FileNotFoundError(name)
    return p


def make_body(spec):
    m = spec['macro']
    h = HumanService.create_human(mask_helpers=False)
    for k, v in m.items():
        if k != 'race':
            HumanObjectProperties.set_value(k, v, entity_reference=h)
    for k, v in m.get('race', {}).items():
        HumanObjectProperties.set_value(k, v, entity_reference=h)
    TargetService.reapply_macro_details(h)
    for name, w in spec.get('targets', {}).items():
        TargetService.load_target(h, target_path(name), weight=w)
    TargetService.bake_targets(h)
    h.name = 'Body'
    return h


def unit_keys(h, race):
    """Load the MakeHuman facial units as shape keys on the baked body."""
    if not h.data.shape_keys:
        h.shape_key_add(name='Basis', from_mix=False)
    keys = {}
    for f in sorted((UNITS / race).glob('*.target.gz')):
        n = f.name.replace('.target.gz', '')
        keys[n] = TargetService.load_target(h, str(f), weight=0.0, name='u_' + n)
    return keys


EXPRESSIONS = {
    # VRM preset: {unit: weight}
    'aa': {'mouth-open': 0.75, 'mouth-part-later': 0.2},
    'ih': {'mouth-open': 0.25, 'mouth-part-later': 0.6, 'mouth-retraction': 0.3},
    'ou': {'mouth-open': 0.25, 'mouth-pursing': 0.8, 'mouth-protusion': 0.5},
    'ee': {'mouth-open': 0.2, 'mouth-retraction': 0.7, 'mouth-upward-retraction': 0.3},
    'oh': {'mouth-open': 0.55, 'mouth-pursing': 0.55},
    'blink': {'eye-left-closure': 1.0, 'eye-right-closure': 1.0},
    'blinkLeft': {'eye-left-closure': 1.0},
    'blinkRight': {'eye-right-closure': 1.0},
    # a real smile narrows the eyes only a little (the cheeks push up), it does not close them
    'happy': {'mouth-corner-puller': 0.8, 'eye-left-slit': 0.18, 'eye-right-slit': 0.18, 'mouth-upward-retraction': 0.15,
              'eyebrows-left-extern-up': 0.12, 'eyebrows-right-extern-up': 0.12, 'nose-left-elevation': 0.15, 'nose-right-elevation': 0.15},
    'relaxed': {'mouth-corner-puller': 0.4, 'eye-left-slit': 0.06, 'eye-right-slit': 0.06},
    'surprised': {'eyebrows-left-up': 0.9, 'eyebrows-right-up': 0.9, 'eye-left-opened-up': 0.6, 'eye-right-opened-up': 0.6,
                  'mouth-open': 0.35},
    'sad': {'eyebrows-left-inner-up': 0.8, 'eyebrows-right-inner-up': 0.8, 'mouth-depression': 0.5},
    'angry': {'eyebrows-left-down': 0.8, 'eyebrows-right-down': 0.8, 'mouth-compression': 0.4},
}


def bake_expressions(h, keys):
    for name, mix in EXPRESSIONS.items():
        for k in keys.values():
            k.value = 0.0
        for u, w in mix.items():
            keys[u].value = w
        sk = h.shape_key_add(name=name, from_mix=True)
        sk.value = 0.0
    for k in list(keys.values()):
        h.shape_key_remove(k)


def sink_tongue(body, mask, teeth=None, back=0.012, down=0.007):
    """The tongue does not follow the jaw in the expression units, so when the mouth opens it shows
    between the teeth. Sit it lower and further back, and in every shape key move it with the lower
    teeth so it stays inside the mouth."""
    idx = np.where(mask)[0]
    kbs = body.data.shape_keys.key_blocks
    basis = kbs[0]
    rest = np.array([basis.data[i].co[:] for i in idx]) + np.array([0, back, -down])
    tid = np.where(teeth)[0] if teeth is not None else []
    t0 = np.array([basis.data[i].co[:] for i in tid]) if len(tid) else None
    for kb in kbs:
        d = np.zeros(3)
        if t0 is not None and kb != basis:
            d = (np.array([kb.data[i].co[:] for i in tid]) - t0).mean(0)
        for k, i in enumerate(idx):
            kb.data[i].co = rest[k] + d
    for k, i in enumerate(idx):
        body.data.vertices[i].co = rest[k]


def strip_body(info, covered):
    """One pass over the body: drop faces hidden under clothes and the helper geometry we don't use."""
    keep = info.isbody.copy()
    for k in ('helper-upper-teeth', 'helper-lower-teeth', 'helper-tongue', 'helper-l-eyelashes-1', 'helper-l-eyelashes-2',
              'helper-r-eyelashes-1', 'helper-r-eyelashes-2'):
        keep |= info.groups[k]
    me = info.body.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    dead_v = [v for v in bm.verts if not keep[v.index]]
    dead_f = [f for f in bm.faces if all(covered[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead_f, context='FACES_ONLY')
    bmesh.ops.delete(bm, geom=dead_v, context='VERTS')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(me)
    bm.free()


def add_eyes(body):
    eyes = HumanService.add_mhclo_asset(str(MH / 'eyes' / 'high-poly' / 'high-poly.mhclo'), body, asset_type='Eyes',
                                        subdiv_levels=0, material_type='MAKESKIN')
    eyes.name = 'Eyes'
    # drop the cornea shell (it maps to the transparent corner of the texture and would hide the iris)
    bm = bmesh.new(); bm.from_mesh(eyes.data)
    uv = bm.loops.layers.uv.active
    dead = [f for f in bm.faces if np.mean([l[uv].uv[0] for l in f.loops]) > 0.82 and np.mean([l[uv].uv[1] for l in f.loops]) < 0.18]
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    bm.to_mesh(eyes.data); bm.free()
    print('cornea faces removed', len(dead))
    return eyes


def face_groups(body):
    """Material slots on the body: 0 skin, 1 teeth, 2 tongue, 3 lashes."""
    names = {vg.index: vg.name for vg in body.vertex_groups}
    slot = np.zeros(len(body.data.vertices), int)
    for v in body.data.vertices:
        for g in v.groups:
            n = names[g.group]
            if g.weight > 0.5 and n.startswith('helper-'):
                slot[v.index] = 1 if 'teeth' in n else 2 if 'tongue' in n else 3 if 'eyelashes' in n else 0
    for p in body.data.polygons:
        p.material_index = int(max(slot[i] for i in p.vertices))
    return slot


def group_mask(obj, name, thr=0.5):
    vg = obj.vertex_groups.get(name)
    m = np.zeros(len(obj.data.vertices), bool)
    if vg is None:
        return m
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index and g.weight > thr:
                m[v.index] = True
    return m


def hair_region(body, rig, eyes, headm, hs):
    """Scalp vertices above a hairline that sits high on the forehead, above the ears and low at the nape.
    Returns (mask, soft) where soft fades out 1.5 cm below the line (for painting the skin)."""
    co = np.array([v.co[:] for v in body.data.vertices])
    ez = np.array([v.co[2] for v in eyes.data.vertices]).mean()
    yc = float(rig.data.bones['head'].head_local[1])
    c = -(co[:, 1] - yc) / (np.hypot(co[:, 0], co[:, 1] - yc) + 1e-9)       # 1 front, -1 back
    h = np.where(c > 0, hs.get('hl_side', 0.02) + (hs.get('hl_front', 0.07) - hs.get('hl_side', 0.02)) * c,
                 hs.get('hl_side', 0.02) + (hs.get('hl_side', 0.02) - hs.get('hl_back', -0.07)) * c)
    d = co[:, 2] - (ez + h)
    return headm & (d > 0), np.where(headm, np.clip(d / 0.015 + 1, 0, 1), 0)


def iris_texture(spec, outdir):
    """MakeHuman's brown eye recoloured: the iris to a natural dark brown (the stock one reads red on
    screen), the sclera a touch off-white."""
    from PIL import Image
    import colorsys
    im = np.asarray(Image.open(str(MH / 'eyes' / 'materials' / 'brown_eye.png')).convert('RGB')).astype(np.float32) / 255
    mx, mn = im.max(-1), im.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    lum = im.mean(-1)
    tgt = np.array(spec.get('iris', (0.30, 0.18, 0.10)), np.float32)       # brown at the iris' median brightness
    iris = ((sat > 0.25) & (lum < 0.4))[..., None]
    rec = tgt[None, None] * (lum[..., None] / 0.11) ** 0.8
    out = np.where(iris, np.clip(rec, 0, 1), im * np.array([0.97, 0.95, 0.94]))
    p = f"{outdir}/{spec['name']}_iris.png"
    Image.fromarray((out * 255).astype(np.uint8)).save(p)
    return p


def dress(spec, body, eyes, clothes, hairs, outdir):
    import skin
    C = spec['colors']
    texdir = outdir
    def fab(name, kind, color, scale, rough, seed=0, var=1.0):
        a, n = skin.fabric(kind, color, seed=seed)
        a = np.array(color)[None, None] + (a - np.array(color)[None, None]) * var
        A = skin.to_image(f"{spec['name']}_{name}_alb", a, f"{texdir}/{spec['name']}_{name}_alb.png")
        N = skin.to_image(f"{spec['name']}_{name}_nrm", n, f"{texdir}/{spec['name']}_{name}_nrm.png")
        return skin.material(name, tex=A, normal=N, rough=rough, scale=scale, nstrength=0.15)
    suit = fab('Suit', 'twill', C['suit'], 18, 0.86, 1, 0.6)
    mats = {'Jacket': suit, 'Trousers': suit,
            'Lapels': fab('Lapel', 'twill', [c * 0.92 for c in C['suit']], 18, 0.8, 2, 0.6),
            'Shirt': fab('Shirt', 'weave', C['shirt'], 24, 0.55, 3, 0.4),
            'Collar': None, 'Belt': skin.material('Belt', base=C.get('belt', (0.03, 0.025, 0.02)), rough=0.35),
            'Shoes': skin.material('Shoes', base=C.get('shoes', (0.02, 0.02, 0.022)), rough=0.22),
            'Button': skin.material('Button', base=[c * 0.6 for c in C['suit']], rough=0.3)}
    mats['Flaps'] = mats['Welt'] = suit
    mats['PocketSquare'] = mats['Shirt']
    mats['Collar'] = mats['CollarPoints'] = mats['Shirt']
    if 'Tie' in clothes:
        mats['Tie'] = mats['Knot'] = fab('Tie', 'twill', C['tie'], 30, 0.62, 4, 0.8)
    for k, o in clothes.items():
        skin.set_material(o, mats[k])
    # body: painted skin + teeth, tongue, lashes
    face_groups(body)
    body.data.materials.clear()
    S = skin.paint_skin(body, spec, texdir)
    body.data.materials.append(skin.material('Skin', tex=S, rough=0.5))
    body.data.materials.append(skin.material('Teeth', base=(0.86, 0.84, 0.78), rough=0.3))
    body.data.materials.append(skin.material('Tongue', base=(0.55, 0.22, 0.24), rough=0.4))
    body.data.materials.append(skin.material('Lashes', base=tuple(c * 0.5 for c in spec['hair']['color']), rough=0.6, double=True))
    eimg = bpy.data.images.load(iris_texture(spec, texdir))
    skin.set_material(eyes, skin.material('Eye', tex=eimg, rough=0.05))
    rgb, alpha = __import__('hair').strand_texture(spec['hair']['color'])
    H = skin.to_image(f"{spec['name']}_hair", rgb, f"{texdir}/{spec['name']}_hair.png", alpha=alpha)
    for o in hairs:
        if o.name.startswith('HairCap'):
            capimg = skin.to_image(f"{spec['name']}_cap", np.ones((8, 8, 3)) * np.array(spec['hair']['color']) * 0.8, f"{texdir}/{spec['name']}_cap.png")
            skin.set_material(o, skin.material('HairCap', tex=capimg, rough=0.7))
        elif o.name.startswith('HairBob'):
            rgb2, a2 = __import__('hair').long_strands(spec['hair']['color'])
            B = skin.to_image(f"{spec['name']}_bob", rgb2, f"{texdir}/{spec['name']}_bob.png", alpha=a2)
            matte = spec['hair'].get('bob', {}).get('classic')
            skin.set_material(o, skin.material('HairBobMatte' if matte else 'HairBob', tex=B, rough=0.68, alpha_tex='self', double=True))
        else:
            skin.set_material(o, skin.material('Hair', tex=H, rough=0.62, alpha_tex='self', double=True))


if __name__ == '__main__':
    import garments, skin, hair, vrmexport
    spec = json.loads(Path(sys.argv[1]).read_text())
    outvrm = sys.argv[2]
    outdir = str(Path(outvrm).parent)
    body = make_body(spec)
    rig = HumanService.add_builtin_rig(body, 'game_engine')
    rig.name = 'Armature'
    eyes = add_eyes(body)
    skin.tag_vertices(body, str(MPFB / 'data' / 'targets'))
    keys = unit_keys(body, spec.get('race_units', 'caucasian'))
    bake_expressions(body, keys)
    info = garments.BodyInfo(body, rig)
    sink_tongue(body, info.groups['helper-tongue'], info.groups['helper-lower-teeth'])
    clothes, covered = garments.suit(info, spec.get('outfit', 'host'))
    THICK = {'Shirt': 0.0016, 'Collar': 0.0025, 'CollarPoints': 0.002, 'Jacket': 0.0045, 'Lapels': 0.003,
             'Trousers': 0.0035, 'Belt': 0.004, 'Tie': 0.004, 'Flaps': 0.003, 'Welt': 0.002, 'PocketSquare': 0.002}
    for k, o in clothes.items():
        if k in THICK:   # shirt and shoes are already dense; the rest get one level of rounding
            garments.finish(o, THICK[k], levels=0 if k in ('Shirt', 'Shoes') else 1)
    strip_body(info, covered)
    for o in clothes.values():   # clothes follow the torso, never the jaw or head
        vg = o.vertex_groups.get('head')
        if vg is not None:
            o.vertex_groups.remove(vg)
    # hair on the rest pose
    headm = group_mask(body, 'head', 0.5)
    scalp, _ = hair_region(body, rig, eyes, headm & ~group_mask(body, 'ears', 0.3), spec['hair'])
    hb = rig.data.bones['head']
    head_c = np.array(hb.head_local) + np.array([0, 0, 0.09])
    hairs = [hair.cap(body, rig, scalp)]
    m = hairs[0].modifiers.get('Armature') or hairs[0].modifiers.new('Armature', 'ARMATURE'); m.object = rig
    collide = headm | group_mask(body, 'neck_01', 0.3) | group_mask(body, 'spine_03', 0.5)
    if spec['hair'].get('bob'):
        ez = float(np.array([v.co[2] for v in eyes.data.vertices]).mean())
        hairs.append(hair.bob(body, rig, head_c, ez, spec['hair']['bob']))
        if not spec['hair']['bob'].get('classic'):   # classic: the plain sculpted bob, no strand strips
            hairs.append(hair.strips(rig, spec['hair']['bob']))
    if spec['hair'].get('cards'):
        hairs.append(hair.grow(body, rig, scalp, collide, spec['hair'], head_c))
    for o in hairs:
        if o.name.startswith('HairBob') and not spec['hair']['bob'].get('classic'):   # rounded hem instead of a paper edge
            garments.finish(o, 0.004, levels=1)
    vrmexport.add_eye_bones(rig, eyes)
    m = eyes.modifiers.get('Armature') or eyes.modifiers.new('Armature', 'ARMATURE'); m.object = rig
    vrmexport.t_pose(rig)
    vrmexport.bake_pose_as_rest(rig)
    spec['_head'] = list(np.array(rig.data.bones['head'].head_local) + np.array([0, 0, 0.09]))
    spec['_eyes'] = [list(rig.data.bones['eye_l'].head_local), list(rig.data.bones['eye_r'].head_local)]
    spec['_scalp'] = hair_region(body, rig, eyes, group_mask(body, 'head', 0.5), spec['hair'])[1]
    dress(spec, body, eyes, clothes, hairs, outdir)
    for o in bpy.data.objects:
        if o.type == 'MESH':
            for p in o.data.polygons:
                p.use_smooth = True
    bpy.ops.wm.save_as_mainfile(filepath=outvrm.replace('.vrm', '.blend'))
    vrmexport.setup_vrm(rig, body, {'name': spec['name']})
    print(vrmexport.export(outvrm))
