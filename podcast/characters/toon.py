"""Build a stylized cartoon talk-show host from simple shapes in Blender (bpy module, headless) and
export it as VRM 1.0: a big round head with drawn features, a rounded suit body, mitten-like hands.

Everything is generated here: the head is a smooth union of ellipsoids, the eyes and mouth are drawn
shapes laid on the face (eye white, iris, lash line; a dark mouth with teeth and tongue). Expressions move
skin-coloured lid patches over the eye and redraw the mouth outline, so each VRM expression is a shape key
on one mesh, and gaze turns the iris discs on two eye bones.

Usage: python toon.py <toon_character.json> <out.vrm> [preview.png]
"""
import sys, json, math, importlib
from pathlib import Path
import bpy, bmesh, addon_utils
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable('bl_ext.user_default.vrm', default_set=True, persistent=True)
import vrmexport

SPEC = json.loads(Path(sys.argv[1]).read_text())
OUT = sys.argv[2]
OUTDIR = str(Path(OUT).parent)
NAME = SPEC['name']
sc = bpy.context.scene
P = SPEC['face']
C = SPEC['colors']


# ---------- small helpers ----------
def mat(name, col, rough=0.5, img=None, glow=0.0, spec=0.5):
    """glow: emission as a fraction of the base colour, so drawn parts stay bright away from the key light."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*col, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Specular IOR Level'].default_value = spec
    t = None
    if img:
        t = m.node_tree.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(img)
        m.node_tree.links.new(t.outputs['Color'], b.inputs['Base Color'])
    if glow:
        b.inputs['Emission Strength'].default_value = glow
        if t:
            m.node_tree.links.new(t.outputs['Color'], b.inputs['Emission Color'])
        else:
            b.inputs['Emission Color'].default_value = (*col, 1)
    return m


def new_obj(name, bm):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o)
    for p in me.polygons:
        p.use_smooth = True
    return o


def ellipsoid(name, c, s, segs=48, axes=None):
    """Ellipsoid at c with radii s; axes (3x3, columns) orients it."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=segs // 2, radius=1.0)
    A = np.eye(3) if axes is None else np.array(axes)
    for v in bm.verts:
        q = A @ (np.array(v.co) * np.array(s))
        v.co = Vector(q + np.array(c))
    return new_obj(name, bm)


def boolean(o, cutter, op='DIFFERENCE'):
    m = o.modifiers.new('b', 'BOOLEAN'); m.object = cutter; m.operation = op; m.solver = 'EXACT'
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier='b')
    bpy.data.objects.remove(cutter)


def ray_ellipsoid(C0, dirs, c, s):
    o = (C0 - np.array(c)) / np.array(s); d = dirs / np.array(s)
    a = (d * d).sum(1); b = 2 * (o * d).sum(1); cc = (o * o).sum() - 1
    disc = b * b - 4 * a * cc
    t = (-b + np.sqrt(np.maximum(disc, 0))) / (2 * a)
    return np.where(disc > 0, t, np.nan)


def blob(name, C0, prims, k=32.0, subdiv=6, smooth=25):
    """A star-shaped smooth union of ellipsoids around C0 (log-sum-exp of their radial extents)."""
    C0 = np.array(C0, float)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    bm.verts.ensure_lookup_table()
    D = np.array([v.co[:] for v in bm.verts]); D /= np.linalg.norm(D, axis=1)[:, None]
    T = np.stack([ray_ellipsoid(C0, D, c, s) for c, s in prims], 1)
    T = np.where(np.isnan(T), 0, T)
    r = np.log(np.exp(k * T).sum(1)) / k
    E = np.array([[e.verts[0].index, e.verts[1].index] for e in bm.edges])
    deg = np.bincount(E.ravel(), minlength=len(r)).astype(float)
    for _ in range(smooth):
        acc = np.zeros_like(r); np.add.at(acc, E[:, 0], r[E[:, 1]]); np.add.at(acc, E[:, 1], r[E[:, 0]])
        r = r + (acc / deg - r) * 0.5
    for v, d, rr in zip(bm.verts, D, r):
        v.co = Vector(C0 + d * rr)
    return new_obj(name, bm)


def tube(name, pts, radii, segs=24, cap=True, flat=None, side=None):
    """A tube through pts (n x 3) with per-point radii, closed with domes at both ends. flat squashes the
    cross-section along the frame's first axis, which is perpendicular to `side` when that is given."""
    pts = np.array(pts, float); radii = np.array(radii, float)
    bm = bmesh.new(); rings = []
    n = len(pts)
    up = np.array([0, 0, 1.0])
    for i in range(n):
        t = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]; t /= np.linalg.norm(t)
        if side is not None:
            b = np.array(side, float) - t * (np.array(side, float) @ t); b /= np.linalg.norm(b); a = np.cross(b, t)
        else:
            a = up - t * (up @ t)
            if np.linalg.norm(a) < 1e-4:
                a = np.array([0, 1.0, 0]) - t * t[1]
            a /= np.linalg.norm(a); b = np.cross(t, a)
        fz = flat[i] if flat is not None else 1.0
        ring = [bm.verts.new(pts[i] + radii[i] * (math.cos(2 * math.pi * j / segs) * a * fz + math.sin(2 * math.pi * j / segs) * b))
                for j in range(segs)]
        rings.append(ring)
    for i in range(n - 1):
        for j in range(segs):
            bm.faces.new((rings[i][j], rings[i][(j + 1) % segs], rings[i + 1][(j + 1) % segs], rings[i + 1][j]))
    if cap:
        for end, sgn in ((0, -1), (n - 1, 1)):
            t = pts[end] - pts[end - sgn] if n > 1 else np.array([1, 0, 0.0])
            t = t / np.linalg.norm(t)
            prev = rings[end]
            for k_ in range(1, 4):   # a dome
                ang = k_ / 4 * math.pi / 2
                ring = [bm.verts.new(pts[end] + (np.array(v.co) - pts[end]) * math.cos(ang) + t * radii[end] * math.sin(ang)) for v in rings[end]]
                for j in range(segs):
                    f = (prev[j], prev[(j + 1) % segs], ring[(j + 1) % segs], ring[j])
                    bm.faces.new(f if sgn > 0 else f[::-1])
                prev = ring
            tip = bm.verts.new(pts[end] + t * radii[end])
            for j in range(segs):
                f = (prev[j], prev[(j + 1) % segs], tip)
                bm.faces.new(f if sgn > 0 else f[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return new_obj(name, bm)


def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active; o.name = name; o.data.name = name
    return o


def tag(o, group):
    vg = o.vertex_groups.new(name=group); vg.add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')


# =====================================================================================
# HEAD (built at design scale around the origin: eyes at z~0, face toward -y)
# =====================================================================================
hx, hy, hz = P['head']
C0 = np.array([0, 0.0, -0.01])
head = blob('Head', C0, [((0, 0.012, 0.03), (hx, hy, hz)),
                         ((0, -0.02, -0.035), (0.08 * P['jaw'], 0.078, 0.07 + P.get('long', 0.0))),
                         ((0.042, -0.04, -0.042), (0.04, 0.042, 0.036)), ((-0.042, -0.04, -0.042), (0.04, 0.042, 0.036)),
                         (P['chin'][:3], (P['chin'][3] * 1.2, P['chin'][3], P['chin'][3]))])
bvh = BVHTree.FromObject(head, bpy.context.evaluated_depsgraph_get())


def surface_y(x, z):
    hit = bvh.ray_cast(Vector((x, -0.5, z)), Vector((0, 1, 0)))
    return hit[0].y if hit[0] else -0.1


face_parts = []          # (object, material name) of everything joined into the Body mesh
head_parts = []          # objects that ride on the head bone

ny = surface_y(0, -0.03)
nose = ellipsoid('Nose', (0, ny + 0.002, -0.03), (P['nose'], P['nose'] * 1.1, P['nose'] * 0.9), 32)
ears = [ellipsoid('Ear', (sg * 0.112, 0.01, -0.018), (0.014, 0.022, 0.03), 32) for sg in (1, -1)]

# ---- eyes: drawn on the face, in layers just in front of the skin ----
# Each eye is an outline (upper and lower curves meeting at the corners) filled with eye white, an iris
# disc on its own bone for gaze, a lash line along the upper curve, and two skin-coloured lid patches that
# are thin slivers at rest; closing the eye stretches them over it, so the eye is cut off cleanly.
R = P['eye_r']
EW, EHU, EHL = P['eye_w'], P['eye_hu'], P['eye_hl']     # half width, height above / below the centre
RI = P['iris_r']
LASH = P['lash']
TILT = P.get('eye_tilt', 0.002)                          # outer corner raised by this much
L_WHITE, L_IRIS, L_LID, L_LASH = 0.0004, 0.0015, 0.0025, 0.0031
NU = 48
U = np.cos(np.linspace(math.pi, 0, NU + 1))           # -1 (inner corner) .. 1 (outer), denser at the corners


def eye_curves(key, side):
    """Upper and lower curves (z offsets from the eye centre, over U) for one eye under an expression."""
    up = EHU * (1 - U * U) ** 0.55 + TILT * U
    lo = -EHL * (1 - U * U) ** 0.7 + TILT * U
    rest = (up.copy(), lo.copy())
    if key in ('blink', 'blink' + side):
        up = lo + 0.0003
    elif key == 'happy':                                  # a smiling squint: the lower lid pushes up
        h = up - lo
        up = up - 0.12 * h; lo = lo + 0.32 * h * (1 - U * U) ** 0.5
    elif key == 'relaxed':
        h = up - lo
        up = up - 0.14 * h; lo = lo + 0.06 * h
    elif key == 'sad':                                    # lid slants down toward the outer corner
        up = up - (up - lo) * (0.06 + 0.22 * (1 + U) / 2)
    elif key == 'angry':                                  # and toward the inner corner
        h = up - lo
        up = up - h * (0.05 + 0.3 * (1 - U) / 2); lo = lo + 0.08 * h
    return up, lo, rest


def eye_xz(sg, cx, cz, u, dz):
    return cx + sg * EW * u, cz + dz


def onface_pts(xs, zs, lift):
    return np.array([[x, surface_y(x, z) - lift, z] for x, z in zip(xs, zs)])


def strip(name, n_u, n_v):
    bm = bmesh.new()
    vs = [[bm.verts.new((0, 0, 0)) for _ in range(n_u)] for _ in range(n_v)]
    for i in range(n_v - 1):
        for j in range(n_u - 1):
            bm.faces.new((vs[i][j], vs[i][j + 1], vs[i + 1][j + 1], vs[i + 1][j]))
    return new_obj(name, bm)


def eye_strip(sg, cx, cz, bottom, top, lift, nv, us=U):
    rows = []
    for i in range(nv):
        f = i / (nv - 1)
        z = bottom + (top - bottom) * f
        x = cx + sg * EW * us
        rows.append(onface_pts(x, cz + z, lift))
    return np.concatenate(rows)


eye_c, eye_parts = [], []        # eye_c: the gaze pivot of each eye
EYE_KEYS = ['blink', 'blinkLeft', 'blinkRight', 'happy', 'relaxed', 'sad', 'angry']


def face_toward_camera(o):
    """Flip a drawn layer's faces if they point into the head (they are built in arbitrary winding)."""
    me = o.data; me.update()
    ny = np.mean([p.normal.y for p in me.polygons])
    if ny > 0:
        bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.reverse_faces(bm, faces=bm.faces); bm.to_mesh(me); bm.free()


def make_eye(sg):
    side = 'Left' if sg > 0 else 'Right'                  # character's left is +x
    cx, cz = sg * P['eye_x'], P['eye_z']
    up0, lo0, _ = eye_curves('rest', side)
    # eye white: a fan from the centre to the outline
    xs = np.concatenate([cx + sg * EW * U, cx + sg * EW * U[::-1][1:-1]])
    zs = np.concatenate([cz + up0, cz + lo0[::-1][1:-1]])
    n = len(xs); bm = bmesh.new()
    ctr = bm.verts.new(onface_pts([cx], [cz], L_WHITE)[0])
    rings = []
    for r in (0.35, 0.7, 1.0):
        rings.append([bm.verts.new(q) for q in onface_pts(cx + (xs - cx) * r, cz + (zs - cz) * r, L_WHITE)])
    for j in range(n):
        bm.faces.new((ctr, rings[0][j], rings[0][(j + 1) % n]))
    for a, b in zip(rings[:-1], rings[1:]):
        for j in range(n):
            bm.faces.new((a[j], b[j], b[(j + 1) % n], a[(j + 1) % n]))
    white = new_obj('EyeWhite', bm)
    # iris: a polar disc, clipped to the outline, on the eye bone
    ic = np.array([cx - sg * 0.0008, cz - 0.0012])
    bm = bmesh.new(); NA, NR_ = 48, 10
    c0 = bm.verts.new((0, 0, 0)); ring_prev = None; uvs = {c0: (0.5, 0.5)}
    grid = []
    for r in range(1, NR_ + 1):
        ring = []
        for a in range(NA):
            th = 2 * math.pi * a / NA
            v = bm.verts.new((0, 0, 0)); uvs[v] = (0.5 + 0.5 * r / NR_ * math.cos(th), 0.5 + 0.5 * r / NR_ * math.sin(th))
            ring.append(v)
        grid.append(ring)
    for a in range(NA):
        bm.faces.new((c0, grid[0][a], grid[0][(a + 1) % NA]))
    for ra, rb in zip(grid[:-1], grid[1:]):
        for a in range(NA):
            bm.faces.new((ra[a], rb[a], rb[(a + 1) % NA], ra[(a + 1) % NA]))
    for v in bm.verts:
        du, dv = uvs[v]
        x = ic[0] + (du - 0.5) * 2 * RI; z = ic[1] + (dv - 0.5) * 2 * RI
        u = np.clip((x - cx) * sg / EW, -0.97, 0.97)
        z = np.clip(z, cz + np.interp(u, U, lo0) + 0.0004, cz + np.interp(u, U, up0) - 0.0004)
        x = cx + sg * EW * u if abs((x - cx) / EW) > 0.97 else x
        v.co = Vector(onface_pts([x], [z], L_IRIS)[0])
    uvl = bm.loops.layers.uv.new('UVMap')
    for f in bm.faces:
        for l in f.loops:
            l[uvl].uv = uvs[l.vert]
    iris = new_obj('Iris', bm)
    tag(iris, f'eye_{"l" if sg > 0 else "r"}')
    # lid patches and lash lines, all reshaped per expression
    NV = 6
    m_ = 0.0006
    lid_u = strip('LidU', NU + 1, NV); lid_l = strip('LidL', NU + 1, NV)
    UL = np.concatenate([[-1.0], U[1:], [1.08, 1.16]])      # the lash runs a little past the outer corner
    lash = strip('Lash', len(UL), 3); lash_lo = strip('LashLo', NU + 1, 2)

    def curves(k):
        up, lo, _ = eye_curves(k, side)
        return up, lo

    def lid_u_co(k):
        up, lo = curves(k)
        return eye_strip(sg, cx, cz, up, up0 + m_, L_LID, NV)

    def lid_l_co(k):
        up, lo = curves(k)
        return eye_strip(sg, cx, cz, lo0 - m_, lo, L_LID, NV)

    def lash_co(k):
        up, lo = curves(k)
        ue = np.concatenate([up, [up[-1] + 0.2 * EHU * 0.08, up[-1] + 0.2 * EHU * 0.22]])
        w = (0.45 + 0.55 * np.clip((UL + 1) / 2, 0, 1) ** 1.3) * np.clip((UL + 1) / 0.25, 0.25, 1)
        w[-2:] = [0.75, 0.25]
        th = LASH * w
        return eye_strip(sg, cx, cz, ue - 0.25 * th, ue + 0.75 * th, L_LASH, 3, us=UL)

    def lash_lo_co(k):
        up, lo = curves(k)
        th = LASH * 0.28 * np.clip((U + 0.2) / 1.2, 0, 1)
        return eye_strip(sg, cx, cz, lo - th * 0.5, lo + th * 0.5, L_LASH, 2)

    for o, fn in ((lid_u, lid_u_co), (lid_l, lid_l_co), (lash, lash_co), (lash_lo, lash_lo_co)):
        o.data.vertices.foreach_set('co', fn('rest').ravel()); o.data.update()
        face_toward_camera(o)
        eye_parts.append((o, fn))
    face_toward_camera(white); face_toward_camera(iris)
    eye_parts.append((white, None)); eye_parts.append((iris, None))
    # both eyes pivot about the middle of the head, so gaze slides each iris along the curved face
    eye_c.append(np.array([sg * 0.001, 0.0, cz]))


for sg in (1, -1):
    make_eye(sg)


def eye_texture():
    S = 512
    im = Image.new('RGBA', (S, S), (0, 0, 0, 255)); d = ImageDraw.Draw(im)
    c = S / 2; ri = S * 0.5
    ir = np.array(P['iris']) * 255
    for k in range(80):          # dark rim, warm lighter lower half
        t = k / 79; r = ri * (1 - t)
        col = ir * (0.35 + 0.95 * t ** 0.6)
        d.ellipse((c - r, c - r + t * S * 0.06, c + r, c + r + t * S * 0.06), fill=tuple(int(min(255, x)) for x in col) + (255,))
    rp = ri * 0.5
    d.ellipse((c - rp, c - rp, c + rp, c + rp), fill=(14, 9, 7, 255))
    hr = ri * 0.24; hx_, hy_ = c - ri * 0.36, c - ri * 0.36
    d.ellipse((hx_ - hr, hy_ - hr, hx_ + hr, hy_ + hr), fill=(255, 255, 255, 255))
    hr2 = ri * 0.1; d.ellipse((c + ri * 0.38 - hr2, c + ri * 0.34 - hr2, c + ri * 0.38 + hr2, c + ri * 0.34 + hr2), fill=(255, 255, 255, 255))
    im = im.filter(ImageFilter.GaussianBlur(1.0)).convert('RGB')
    p = f'{OUTDIR}/{NAME}_eye.png'; im.save(p); return p


# ---- brows ----
def curve_mesh(name, pts, bevel, lift=0.0015):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = bevel; cu.bevel_resolution = 3
    cu.use_fill_caps = True
    sp = cu.splines.new('BEZIER'); sp.bezier_points.add(len(pts) - 1)
    for bp, (x, z, w) in zip(sp.bezier_points, pts):
        bp.co = (x, surface_y(x, z) - lift, z); bp.handle_left_type = bp.handle_right_type = 'AUTO'; bp.radius = w
    o = bpy.data.objects.new(name, cu); sc.collection.objects.link(o)
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.convert(target='MESH')
    return bpy.context.view_layer.objects.active


bz = P['eye_z'] + R * 1.55
brows = [curve_mesh('Brow', [(sg * 0.02, bz + 0.001, 1.0), (sg * 0.04, bz + 0.006, 1.0), (sg * 0.06, bz + 0.003, 0.6)], P['brow'])
         for sg in (1, -1)]

# ---- mouth: a dark shape on the face whose outline is redrawn per expression ----
MZ = P.get('mouth_z', -0.068)
NT, NR = 40, 4


def mouth_outline(w, hu, hl, smile, dz=0.0):
    t = np.cos(np.linspace(math.pi, 0, NT // 2 + 1))            # -1 .. 1, denser at the corners
    up = MZ + dz + smile * t ** 2 + hu * np.sqrt(np.clip(1 - t * t, 0, 1))
    lo = MZ + dz + smile * t ** 2 - hl * np.clip(1 - t * t, 0, 1) ** 0.6
    xs = np.concatenate([w * t, w * t[::-1][1:-1]])
    zs = np.concatenate([up, lo[::-1][1:-1]])
    return xs, zs, (w * t, up, lo)


def onface(x, z, lift):
    return np.array([[xi, surface_y(xi, zi) - lift, zi] for xi, zi in zip(x, z)])


def fan_coords(xs, zs, lift):
    cx, cz = xs.mean(), zs.mean()
    X, Z = [cx], [cz]
    for r in range(1, NR + 1):
        f = r / NR
        X += list(cx + (xs - cx) * f); Z += list(cz + (zs - cz) * f)
    return onface(np.array(X), np.array(Z), lift)


def fan_mesh(name, n):
    bm = bmesh.new()
    vs = [bm.verts.new((0, 0, 0)) for _ in range(1 + NR * n)]
    for j in range(n):
        bm.faces.new((vs[0], vs[1 + j], vs[1 + (j + 1) % n]))
    for r in range(1, NR):
        a, b = 1 + (r - 1) * n, 1 + r * n
        for j in range(n):
            bm.faces.new((vs[a + j], vs[b + j], vs[b + (j + 1) % n], vs[a + (j + 1) % n]))
    return new_obj(name, bm)


def strip_coords(top_x, top_z, h, lift, scale=0.8, below=True):
    x = top_x * scale; z = np.interp(x, top_x, top_z) - (0.0006 if below else -0.0006) * np.sign(h + 1e-9)
    z2 = z - h if below else z + h
    xs = np.concatenate([x, x[::-1]]); zs = np.concatenate([z, z2[::-1]])
    return fan_coords(xs, zs, lift)


MOUTH = {   # w, hu, hl, smile, dz
    'rest': (0.022, 0.0009, 0.0015, 0.004, 0), 'aa': (0.02, 0.003, 0.014, 0.002, 0), 'ih': (0.024, 0.002, 0.006, 0.004, 0),
    'ou': (0.011, 0.004, 0.007, 0.0, 0), 'ee': (0.026, 0.002, 0.006, 0.005, 0), 'oh': (0.015, 0.005, 0.012, 0.001, 0),
    'happy': (0.028, 0.0012, 0.008, 0.009, 0.001), 'relaxed': (0.024, 0.0006, 0.0012, 0.006, 0),
    'surprised': (0.012, 0.004, 0.01, 0.0, -0.001), 'sad': (0.018, 0.0006, 0.0011, -0.004, 0),
    'angry': (0.02, 0.0005, 0.0012, -0.003, 0),
}


def mouth_state(key):
    w, hu, hl, sm, dz = MOUTH.get(key, MOUTH['rest'])
    w *= P.get('mouth_w', 1.0)
    xs, zs, (tx, up, lo) = mouth_outline(w, hu, hl, sm, dz)
    o = hu + hl
    m = fan_coords(xs, zs, 0.0010)
    teeth = strip_coords(tx, up, min(0.0035, max(0, 0.35 * (o - 0.003))), 0.0014, 0.78)
    tongue = strip_coords(tx, lo, min(0.004, max(0, 0.35 * (o - 0.004))), 0.0012, 0.55, below=False)
    return m, teeth, tongue


m0, t0, g0 = mouth_state('rest')
mouth = fan_mesh('Mouth', NT); teeth = fan_mesh('Teeth', (len(t0) - 1) // NR)
tongue = fan_mesh('Tongue', (len(g0) - 1) // NR)
for o, co in ((mouth, m0), (teeth, t0), (tongue, g0)):
    o.data.vertices.foreach_set('co', co.ravel()); o.data.update()

# ---- skin texture: plain skin with soft cheek blush, mapped spherically around C0 ----
TEX = 512


def sph_uv(p):
    d = (np.array(p) - C0); d /= np.linalg.norm(d)
    return 0.5 + math.atan2(d[0], -d[1]) / (2 * math.pi), 1 - math.acos(np.clip(d[2], -1, 1)) / math.pi


def skin_texture():
    base = np.array(C['skin'])
    U, V = np.meshgrid((np.arange(TEX) + 0.5) / TEX, (np.arange(TEX // 2) + 0.5) / (TEX // 2))
    img = np.tile(base, (TEX // 2, TEX, 1))
    for sg in (1, -1):
        bu, bv = sph_uv((sg * 0.056, surface_y(sg * 0.056, -0.042), -0.042))
        g = np.exp(-(((U - bu) / 0.035) ** 2 + ((1 - V - bv) / 0.03) ** 2)) * P.get('blush', 0.3)
        img = img * (1 - g[..., None] * 0.6) + np.array(C.get('blush', (0.95, 0.5, 0.5))) * g[..., None] * 0.6
    img[-4:, -4:] = base        # plain patch for the parts that are not mapped
    p = f'{OUTDIR}/{NAME}_skin.png'
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(p)
    return p


def uv_spherical(o):
    uv = o.data.uv_layers.new(name='UVMap')
    for l in o.data.loops:
        uv.data[l.index].uv = sph_uv(o.data.vertices[l.vertex_index].co)


def uv_flat(o):
    uv = o.data.uv_layers.new(name='UVMap')
    for l in o.data.loops:
        uv.data[l.index].uv = (1 - 1.5 / TEX, 1.5 / TEX)


# ---- hair ----
def hair_mesh():
    if SPEC['hair'] == 'bob':
        shell = blob('Hair', C0, [((0, 0.014, 0.036), (hx * 1.13, hy * 1.15, hz * 1.1)),
                                  ((0.075, 0.02, -0.05), (0.05, 0.085, 0.075)), ((-0.075, 0.02, -0.05), (0.05, 0.085, 0.075)),
                                  ((0, 0.06, -0.05), (0.09, 0.06, 0.08))], k=40)
        boolean(shell, ellipsoid('c', (0, -0.15, -0.047), (0.086, 0.15, 0.108), 64))
        boolean(shell, ellipsoid('c', (0, 0, -0.29), (0.4, 0.4, 0.19), 32))
    else:
        shell = blob('Hair', C0, [((0, 0.016, 0.045), (hx * 1.035, hy * 1.04, hz * 1.05)),
                                  ((-0.025, -0.03, 0.1), (0.085, 0.075, 0.05)), ((0.04, -0.035, 0.09), (0.06, 0.065, 0.045))], k=30)
        ry = math.radians(-10)
        A = [[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]]
        boolean(shell, ellipsoid('c', (0.015, -0.12, -0.068), (0.2, 0.17, 0.15), 64, axes=A))
        boolean(shell, ellipsoid('c', (0, 0.05, -0.17), (0.3, 0.2, 0.19), 32))
    boolean(shell, ellipsoid('c', (0, 0.01, 0.0), (hx * 0.99, hy * 0.99, hz * 1.4), 64))
    m = shell.modifiers.new('s', 'SUBSURF'); m.levels = 1
    bpy.context.view_layer.objects.active = shell; bpy.ops.object.modifier_apply(modifier='s')
    for p in shell.data.polygons:
        p.use_smooth = True
    return shell


hair = hair_mesh()

# ---- expressions on the face parts (design space) ----
KEYS = ['aa', 'ih', 'ou', 'ee', 'oh', 'blink', 'blinkLeft', 'blinkRight', 'happy', 'relaxed', 'surprised', 'sad', 'angry']


def rot_x(co, c, ang):
    q = co - c
    ca, sa = math.cos(ang), math.sin(ang)
    y = q[:, 1] * ca - q[:, 2] * sa; z = q[:, 1] * sa + q[:, 2] * ca
    return np.stack([q[:, 0], y, z], 1) + c


BROW = {'surprised': (0.009, 0.0), 'sad': (0.003, 0.25), 'angry': (-0.004, -0.3), 'happy': (0.003, 0.0), 'relaxed': (0.0, 0.0)}


def add_keys(o, fn):
    """fn(key, rest_coords) -> coords for that key."""
    o.shape_key_add(name='Basis', from_mix=False)
    rest = np.array([v.co[:] for v in o.data.vertices])
    for k in KEYS:
        sk = o.shape_key_add(name=k, from_mix=False)
        sk.data.foreach_set('co', np.asarray(fn(k, rest), float).ravel())


for o, fn in eye_parts:
    add_keys(o, (lambda k, rest, fn=fn: fn(k) if k in EYE_KEYS else rest) if fn else (lambda k, rest: rest))
for b, c in zip(brows, eye_c):
    def f(k, rest, c=c):
        up, tilt = BROW.get(k, (0.0, 0.0))
        q = rest.copy(); q[:, 2] += up
        inner = np.clip(1 - np.abs(q[:, 0] - (c[0] - np.sign(c[0]) * 0.02)) / 0.04, 0, 1)
        q[:, 2] += tilt * 0.02 * (inner - 0.5)
        return q
    add_keys(b, f)
states = {k: mouth_state(k) for k in ['rest'] + KEYS}
for o, idx in ((mouth, 0), (teeth, 1), (tongue, 2)):
    add_keys(o, lambda k, rest, idx=idx: states[k if k in MOUTH else 'rest'][idx])
for o in [head, nose] + ears:
    add_keys(o, lambda k, rest: rest)

# ---- materials and UVs on the face parts ----
skin_tex = skin_texture()
M = {'Skin': mat('Skin', (1, 1, 1), 0.5, img=skin_tex), 'Lash': mat('Lash', (0.03, 0.02, 0.02), 0.6),
     'Brow': mat('Brow', C['hair'], 0.6), 'Mouth': mat('Mouth', (0.3, 0.07, 0.07), 0.6),
     'Teeth': mat('Teeth', (0.97, 0.96, 0.94), 0.4), 'Tongue': mat('Tongue', (0.85, 0.4, 0.42), 0.5),
     'Hair': mat('ToonHair', C['hair'], 0.45)}
for o in (head, nose, *ears):     # (booleans leave empty material slots behind: clear them)
    uv_spherical(o); o.data.materials.clear(); o.data.materials.append(M['Skin'])
    o.data.polygons.foreach_set('material_index', [0] * len(o.data.polygons))
EYE_MAT = {'LidU': 'Skin', 'LidL': 'Skin', 'Lash': 'Lash', 'LashLo': 'Lash', 'EyeWhite': 'EyeWhite', 'Iris': 'Eye'}
M['EyeWhite'] = mat('EyeWhite', (0.97, 0.96, 0.95), 0.9, glow=0.12, spec=0.1)
M['Eye'] = mat('Iris', (1, 1, 1), 0.9, img=eye_texture(), glow=0.1, spec=0.1)
for o, _ in eye_parts:
    kind = o.name.split('.')[0]
    if kind != 'Iris':
        uv_flat(o)
    o.data.materials.append(M[EYE_MAT[kind]])
for b in brows:
    uv_flat(b); b.data.materials.clear(); b.data.materials.append(M['Brow'])
for o, k in ((mouth, 'Mouth'), (teeth, 'Teeth'), (tongue, 'Tongue')):
    uv_flat(o); o.data.materials.append(M[k])
hair.data.materials.clear(); hair.data.materials.append(M['Hair'])
hair.data.polygons.foreach_set('material_index', [0] * len(hair.data.polygons))
uv_flat(hair)

# =====================================================================================
# place the head on the body: scale up and move the neck point onto the neck joint
# =====================================================================================
HS = SPEC.get('head_scale', 1.3)
PIV = np.array([0, 0.012, -0.105])          # where the head meets the neck, in design space
S_ = SPEC.get('scale', 1.0)
SW = SPEC.get('shoulder_w', 0.17)
J = {k: [x * S_ for x in v] for k, v in {
    'pelvis': (0, 0, 0.92), 'spine_01': (0, 0, 1.0), 'spine_02': (0, 0, 1.08), 'spine_03': (0, 0, 1.16),
    'neck': (0, 0.005, 1.30), 'head': (0, 0.012, 1.37), 'head_top': (0, 0.012, 1.62)}.items()}
for side, sg in (('l', 1), ('r', -1)):
    z = 1.27 * S_
    for n, x in (('clav', 0.02), ('upperarm', SW - 0.01), ('lowerarm', SW + 0.235), ('hand', SW + 0.46), ('knuckle', SW + 0.53)):
        J[f'{n}_{side}'] = [sg * x * (S_ if n in ('clav',) else 1), 0, z]
    for n, p in (('thigh', (0.09, 0, 0.92)), ('calf', (0.09, 0, 0.5)), ('foot', (0.09, 0.0, 0.09)), ('ball', (0.09, -0.12, 0.03)),
                 ('toe', (0.09, -0.19, 0.03))):
        J[f'{n}_{side}'] = [sg * p[0], p[1] * S_, p[2] * S_]
J.update(SPEC.get('joints', {}))
NECK_TOP = np.array(J['head'])
Mx = Matrix.Translation(Vector(NECK_TOP)) @ Matrix.Scale(HS, 4) @ Matrix.Translation(Vector(-PIV))
face_objs = [head, nose, *ears, *[o for o, _ in eye_parts], *brows, mouth, teeth, tongue]
for o in face_objs + [hair]:
    o.data.transform(Mx, shape_keys=True); o.data.update()
eye_c = [np.array(Mx @ Vector(c)) for c in eye_c]

# =====================================================================================
# BODY
# =====================================================================================
def jt(n):
    return np.array(J[n], float)


body_skin = []
neck = tube('Neck', [jt('neck') + [0, 0.012, -0.05], jt('head') + [0, 0.012, 0.03]], [0.052, 0.05], 24)
body_skin.append(neck)

# hands: a soft palm, three fingers and a thumb (cartoon hands), per side
hands = []
FING = {}
for side, sg in (('l', 1), ('r', -1)):
    w = jt(f'hand_{side}'); kn = jt(f'knuckle_{side}')
    d = (kn - w) / np.linalg.norm(kn - w)
    palm = ellipsoid('Palm', (w + kn) / 2 + d * 0.004, (0.042, 0.04, 0.016), 32)
    hands.append(palm)
    for fn, off, L in (('index', -0.022, 0.07), ('middle', 0.0, 0.078), ('pinky', 0.022, 0.064)):
        base = kn + np.array([0, off, 0]) - d * 0.006
        pts = [base + d * L * f for f in (0, 0.33, 0.66, 1.0)]
        hands.append(tube('Finger', pts, [0.0105, 0.0102, 0.0098, 0.0094], 16))
        for i in (1, 2, 3):
            FING[f'{fn}_0{i}_{side}'] = (pts[i - 1], pts[i], f'hand_{side}' if i == 1 else f'{fn}_0{i - 1}_{side}')
    tb = w + np.array([0, -0.03, -0.004]) + d * 0.015
    tdir = (d * 0.45 + np.array([0, -0.85, -0.1])); tdir /= np.linalg.norm(tdir)
    hands.append(tube('Thumb', [tb, tb + tdir * 0.025, tb + tdir * 0.048], [0.012, 0.0112, 0.0105], 16))
    FING[f'thumb_01_{side}'] = (w + np.array([0, -0.012, -0.004]), tb, f'hand_{side}')
    FING[f'thumb_02_{side}'] = (tb, tb + tdir * 0.025, f'thumb_01_{side}')
    FING[f'thumb_03_{side}'] = (tb + tdir * 0.025, tb + tdir * 0.048, f'thumb_02_{side}')
body_skin += hands
for o in body_skin:
    uv_flat(o); o.data.materials.append(M['Skin'])
    add_keys(o, lambda k, rest: rest)

# suit jacket: a rounded torso, with shoulders
chest = jt('spine_03'); waist = jt('spine_01'); hip = jt('pelvis')
sw = SW
jacket = blob('Jacket', (chest + waist) / 2 + [0, 0.005, 0], [
    (chest + [0, 0.005, 0.0], (sw * 0.98, 0.105, 0.13)),
    (waist + [0, 0.008, 0.0], (sw * 0.88, 0.1, 0.12)),
    (hip + [0, 0.012, 0.0], (sw * 0.92, 0.11, 0.1)),
    (jt('upperarm_l') + [-0.03, 0.0, -0.01], (0.075, 0.075, 0.07)), (jt('upperarm_r') + [0.03, 0.0, -0.01], (0.075, 0.075, 0.07)),
], k=40, subdiv=6, smooth=10)
jbvh = BVHTree.FromObject(jacket, bpy.context.evaluated_depsgraph_get())


def jacket_front(x, z):
    hit = jbvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)))
    return hit[0].y if hit[0] else 0.0


# sleeves and cuffs
sleeves, cuffs = [], []
for side in ('l', 'r'):
    s = jt(f'upperarm_{side}'); e = jt(f'lowerarm_{side}'); wr = jt(f'hand_{side}')
    pts = [s + (e - s) * f for f in (0.0, 0.5, 1.0)] + [e + (wr - e) * f for f in (0.5, 0.92)]
    sleeves.append(tube('Sleeve', pts, [0.06, 0.054, 0.05, 0.047, 0.046], 28))
    cuffs.append(tube('Cuff', [e + (wr - e) * 0.9, e + (wr - e) * 1.0], [0.04, 0.039], 24))

# shirt front (the open V of the jacket), collar and tie
z_top = chest[2] + 0.105; z_v = chest[2] - SPEC.get('v_depth', 0.1)
vx = SPEC.get('v_width', 0.06)
bib_pts = []
for z in np.linspace(z_v, z_top, 9):
    f = (z - z_v) / (z_top - z_v)
    bib_pts.append((f * vx, z))
bm = bmesh.new()
rows = []
for x_half, z in bib_pts:
    xs = np.linspace(-max(x_half, 0.003), max(x_half, 0.003), 9)
    rows.append([bm.verts.new((x, jacket_front(x, z) - 0.002, z)) for x in xs])
for a, b in zip(rows[:-1], rows[1:]):
    for j in range(8):
        bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
shirt = new_obj('Shirt', bm)
sol = shirt.modifiers.new('t', 'SOLIDIFY'); sol.thickness = 0.003
bpy.context.view_layer.objects.active = shirt; bpy.ops.object.modifier_apply(modifier='t')
collar = tube('Collar', [jt('neck') + [0, 0.012, -0.045], jt('neck') + [0, 0.012, -0.02]], [0.058, 0.056], 28)
shirt = join([shirt, collar] + cuffs, 'Shirt')
lapels = []
for sg in (1, -1):    # the jacket's lapels: darker bands along the V
    pts = []
    for z in np.linspace(z_v, z_top + 0.01, 8):
        f = (z - z_v) / (z_top - z_v)
        x = sg * (f * vx + 0.012)
        pts.append([x, jacket_front(x, z) - 0.003, z])
    lapels.append(tube('Lapel', pts, [0.008 + 0.012 * i / (len(pts) - 1) for i in range(len(pts))], 16, flat=[0.25] * len(pts), side=(1, 0, 0)))
lapel = join(lapels, 'Lapels')
parts_cloth = {'Jacket': jacket, 'Sleeves': join(sleeves, 'Sleeves'), 'Shirt': shirt, 'Lapels': lapel}
if SPEC.get('tie'):
    tpts = [[0, jacket_front(0, z) - 0.006, z] for z in np.linspace(z_top - 0.01, z_v - 0.05, 6)]
    tie = tube('Tie', tpts, [0.011, 0.013, 0.015, 0.017, 0.019, 0.019], 16, flat=[0.3] * 6, side=(1, 0, 0))
    knot = ellipsoid('Knot', [0, jacket_front(0, z_top - 0.012) - 0.01, z_top - 0.012], (0.014, 0.01, 0.012), 20)
    parts_cloth['Tie'] = join([tie, knot], 'Tie')
# trousers and shoes
legs, shoes = [], []
for side in ('l', 'r'):
    th = jt(f'thigh_{side}'); ca = jt(f'calf_{side}'); ft = jt(f'foot_{side}')
    legs.append(tube('Leg', [th + [0, 0, 0.03], th + (ca - th) * 0.5, ca, ca + (ft - ca) * 0.5, ft + [0, 0, 0.03]],
                     [0.085, 0.075, 0.062, 0.056, 0.055], 24))
    toe = jt(f'ball_{side}')
    shoes.append(ellipsoid('Shoe', (ft + toe) / 2 + [0, 0, -0.012], (0.05, 0.11, 0.04), 32))
parts_cloth['Trousers'] = join(legs, 'Trousers')
parts_cloth['Shoes'] = join(shoes, 'Shoes')
cloth_mats = {'Jacket': mat('Suit', C['suit'], 0.7), 'Sleeves': None, 'Shirt': mat('Shirt', C['shirt'], 0.6),
              'Lapels': mat('Lapel', [c * 0.8 for c in C['suit']], 0.6), 'Tie': mat('TieMat', C.get('tie', (0.4, 0.06, 0.09)), 0.5),
              'Trousers': mat('Trouser', C.get('trousers', C['suit']), 0.7), 'Shoes': mat('Shoe', (0.04, 0.03, 0.03), 0.35)}
cloth_mats['Sleeves'] = cloth_mats['Jacket']
for k, o in parts_cloth.items():
    uv_flat(o); o.data.materials.clear(); o.data.materials.append(cloth_mats[k])
    for p in o.data.polygons:
        p.use_smooth = True

# =====================================================================================
# RIG
# =====================================================================================
arm = bpy.data.armatures.new('Armature'); rig = bpy.data.objects.new('Armature', arm); sc.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig; bpy.ops.object.mode_set(mode='EDIT')
BONES = {'pelvis': ('pelvis', 'spine_01', None), 'spine_01': ('spine_01', 'spine_02', 'pelvis'),
         'spine_02': ('spine_02', 'spine_03', 'spine_01'), 'spine_03': ('spine_03', 'neck', 'spine_02'),
         'neck_01': ('neck', 'head', 'spine_03'), 'head': ('head', 'head_top', 'neck_01')}
for s in 'lr':
    BONES.update({f'clavicle_{s}': (f'clav_{s}', f'upperarm_{s}', 'spine_03'), f'upperarm_{s}': (f'upperarm_{s}', f'lowerarm_{s}', f'clavicle_{s}'),
                  f'lowerarm_{s}': (f'lowerarm_{s}', f'hand_{s}', f'upperarm_{s}'), f'hand_{s}': (f'hand_{s}', f'knuckle_{s}', f'lowerarm_{s}'),
                  f'thigh_{s}': (f'thigh_{s}', f'calf_{s}', 'pelvis'), f'calf_{s}': (f'calf_{s}', f'foot_{s}', f'thigh_{s}'),
                  f'foot_{s}': (f'foot_{s}', f'ball_{s}', f'calf_{s}'), f'ball_{s}': (f'ball_{s}', f'toe_{s}', f'foot_{s}')})
BONES.update(FING)
for s_, c in zip('lr', eye_c):
    BONES[f'eye_{s_}'] = (list(c), list(c + np.array([0, -0.02, 0])), 'head')
for n, (h, t, par) in BONES.items():
    b = arm.edit_bones.new(n)
    b.head = Vector(J[h] if isinstance(h, str) else h); b.tail = Vector(J[t] if isinstance(t, str) else t)
for n, (h, t, par) in BONES.items():
    if par:
        arm.edit_bones[n].parent = arm.edit_bones[par]; arm.edit_bones[n].use_connect = False
bpy.ops.object.mode_set(mode='OBJECT')
segs = {n: (np.array(rig.data.bones[n].head_local), np.array(rig.data.bones[n].tail_local)) for n in BONES}


def seg_dist(P_, a, b):
    ab = b - a; t = np.clip(((P_ - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(P_ - (a + t[:, None] * ab), axis=1)


def skin_to(o, bones, sigma=0.05, top=3, radii=None):
    """Weights from the distance to each bone (minus that bone's body radius), Gaussian, best `top` kept."""
    P_ = np.array([v.co[:] for v in o.data.vertices])
    radii = radii or {}
    if len(bones) == 1:
        W = np.ones((len(P_), 1))
    else:
        D = np.stack([np.maximum(0, seg_dist(P_, *segs[b]) - radii.get(b, 0.0)) for b in bones], 1)
        W = np.exp(-(D / sigma) ** 2) + 1e-12
        if top < len(bones):
            idx = np.argsort(-W, 1)[:, top:]
            np.put_along_axis(W, idx, 0, 1)
        W /= W.sum(1, keepdims=True)
    for j, b in enumerate(bones):
        vg = o.vertex_groups.get(b) or o.vertex_groups.new(name=b)
        for i in np.nonzero(W[:, j] > 1e-3)[0]:
            vg.add([int(i)], float(W[i, j]), 'REPLACE')


SPINE = ['pelvis', 'spine_01', 'spine_02', 'spine_03']
for o in face_objs + [hair]:
    if not o.vertex_groups:          # (the irises already ride on their eye bones)
        skin_to(o, ['head'])
skin_to(neck, ['spine_03', 'neck_01', 'head'], 0.04)
TORSO_R = {b: 0.12 for b in SPINE} | {'clavicle_l': 0.03, 'clavicle_r': 0.03}
skin_to(parts_cloth['Jacket'], SPINE + ['clavicle_l', 'clavicle_r', 'upperarm_l', 'upperarm_r'], 0.05, radii=TORSO_R)
for k in ('Shirt', 'Lapels', 'Tie'):
    if k in parts_cloth:
        skin_to(parts_cloth[k], SPINE + ['neck_01', 'lowerarm_l', 'lowerarm_r', 'hand_l', 'hand_r'], 0.05, radii=TORSO_R)
skin_to(parts_cloth['Sleeves'], ['spine_03', 'clavicle_l', 'clavicle_r', 'upperarm_l', 'upperarm_r', 'lowerarm_l', 'lowerarm_r', 'hand_l', 'hand_r'], 0.05)
skin_to(parts_cloth['Trousers'], ['pelvis', 'thigh_l', 'thigh_r', 'calf_l', 'calf_r', 'foot_l', 'foot_r'], 0.06)
skin_to(parts_cloth['Shoes'], ['foot_l', 'foot_r', 'ball_l', 'ball_r'], 0.04)
# hands: palm to the hand bone, each finger to its own chain
hi = 0
for side in ('l', 'r'):
    palm, fi, fm, fp, th = hands[hi:hi + 5]; hi += 5
    skin_to(palm, [f'hand_{side}'])
    for o, fn in ((fi, 'index'), (fm, 'middle'), (fp, 'pinky')):
        skin_to(o, [f'hand_{side}'] + [f'{fn}_0{i}_{side}' for i in (1, 2, 3)], 0.012, 2)
    skin_to(th, [f'hand_{side}', f'thumb_01_{side}', f'thumb_02_{side}', f'thumb_03_{side}'], 0.012, 2)

body = join(face_objs + body_skin, 'Body')
for o in [body, hair] + list(parts_cloth.values()):
    o.parent = rig
    m = o.modifiers.new('Armature', 'ARMATURE'); m.object = rig

bpy.ops.wm.save_as_mainfile(filepath=OUT.replace('.vrm', '.blend'))
for k, v in list(vrmexport.HUMANOID.items()):     # cartoon hands have no ring finger
    if v not in rig.data.bones:
        del vrmexport.HUMANOID[k]
vrmexport.setup_vrm(rig, body, {'name': NAME})
eye_mid = (eye_c[0] + eye_c[1]) / 2 - np.array(rig.data.bones['head'].head_local)
ext = __import__('bl_ext.user_default.vrm.editor.extension_accessor', fromlist=['x']).get_armature_extension(rig.data)
la = ext.vrm1.look_at
la.offset_from_head_bone = (0.0, float(eye_mid[2]), float(-eye_mid[1]))
# the eye bones pivot in the middle of the head, so a small turn slides the drawn iris across the eye
for rm, deg in ((la.range_map_horizontal_inner, 2.5), (la.range_map_horizontal_outer, 2.5),
                (la.range_map_vertical_down, 1.2), (la.range_map_vertical_up, 0.8)):
    rm.input_max_value = 90.0; rm.output_scale = deg
print(vrmexport.export(OUT))
