"""Clothes cut from the MakeHuman body itself.

Each garment is a copy of the body faces it should cover, pushed out along the body normals,
so it inherits the body's UVs and bone weights and moves with the rig. The tie is built from
scratch on the shirt front.
"""
import math
import bpy, bmesh
import numpy as np
from mathutils import Vector, kdtree

TORSO = {'pelvis', 'spine_01', 'spine_02', 'spine_03', 'clavicle_l', 'clavicle_r'}
ARMS = {'upperarm_l', 'upperarm_r', 'lowerarm_l', 'lowerarm_r'}
LEGS = {'pelvis', 'thigh_l', 'thigh_r', 'calf_l', 'calf_r'}
FEET = {'foot_l', 'foot_r', 'ball_l', 'ball_r'}
NECK = {'neck_01'}


class BodyInfo:
    """Per-vertex position, normal, dominant bone and body/helper flags of the basemesh at rest."""

    def __init__(self, body, rig):
        me = body.data
        n = len(me.vertices)
        self.body, self.rig = body, rig
        self.co = np.array([v.co[:] for v in me.vertices])
        me.calc_normals_split() if hasattr(me, 'calc_normals_split') else None
        self.no = np.array([v.normal[:] for v in me.vertices])
        names = [vg.name for vg in body.vertex_groups]
        bones = set(b.name for b in rig.data.bones)
        self.dom = np.array([''] * n, dtype=object)
        self.isbody = np.zeros(n, bool)
        for v in me.vertices:
            best, bw = '', 0.0
            for g in v.groups:
                nm = names[g.group]
                if nm == 'body' and g.weight > 0.5:
                    self.isbody[v.index] = True
                if nm in bones and g.weight > bw:
                    best, bw = nm, g.weight
            self.dom[v.index] = best
        self.groups = {nm: np.zeros(n, bool) for nm in names}
        for v in me.vertices:
            for g in v.groups:
                if g.weight > 0.5:
                    self.groups[names[g.group]][v.index] = True
        B = rig.data.bones
        self.j = {b.name: (np.array(b.head_local), np.array(b.tail_local)) for b in B}

    def smoothed(self, iters=30, zlo=None, zhi=None):
        """Body positions/normals with fine detail (pecs, nipples, ribs) relaxed away in [zlo, zhi]."""
        key = (iters, zlo, zhi)
        if getattr(self, '_sm_key', None) == key:
            return self._sm
        bm = bmesh.new()
        bm.from_mesh(self.body.data)
        if self.body.data.shape_keys:
            bm.verts.ensure_lookup_table()
            for v in bm.verts:
                v.co = Vector(self.co[v.index])
        bm.verts.ensure_lookup_table()
        skip = np.isin(self.dom, ['head', 'neck_01', 'hand_l', 'hand_r', 'foot_l', 'foot_r', 'ball_l', 'ball_r']) | ~self.isbody
        vs = [v for v in bm.verts if not skip[v.index] and not v.is_boundary]
        for _ in range(iters):   # Taubin: smooth, then un-shrink
            bmesh.ops.smooth_vert(bm, verts=vs, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
            bmesh.ops.smooth_vert(bm, verts=vs, factor=-0.53, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bm.normal_update()
        co = np.array([v.co[:] for v in bm.verts])
        no = np.array([v.normal[:] for v in bm.verts])
        bm.free()
        self._sm_key, self._sm = key, (co, no)
        return co, no

    def z(self, bone, end=0):
        return float(self.j[bone][end][2])

    def along(self, bone):
        """0 at the bone head, 1 at the tail, for every vertex."""
        h, t = self.j[bone]
        d = t - h
        return (self.co - h) @ d / (d @ d)


def dup(src, name):
    o = src.copy()
    o.data = src.data.copy()
    o.name = o.data.name = name
    bpy.context.collection.objects.link(o)
    if o.data.shape_keys:
        o.shape_key_clear()
    for m in list(o.modifiers):
        if m.type != 'ARMATURE':
            o.modifiers.remove(m)
    return o


def cut(info, name, vmask, offset, smooth=0, planes=(), drop=None, subdiv=0, base=None):
    """New object from body faces touching vmask, offset along normals, then trimmed with planes.

    offset: metres, or an array per vertex. planes: (point, normal, region) - geometry on the normal's
    side is removed, only among faces whose centre passes region(centre) (or all faces if None).
    drop(centre, normal) -> True removes a face outright (hidden undersides)."""
    o = dup(info.body, name)
    off = offset if np.ndim(offset) else np.full(len(info.co), offset)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    bco, bno = base if base is not None else (info.co, info.no)
    for v in bm.verts:
        i = v.index
        v.co = Vector(bco[i] + bno[i] * off[i])
    kill = [f for f in bm.faces if not any(vmask[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    if subdiv:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=subdiv, use_grid_fill=True, smooth=0.6)
    for co, no, region in planes:
        faces = [f for f in bm.faces if region is None or region(np.array(f.calc_center_median()))]
        if not faces:
            continue
        geom = list(set(faces) | {e for f in faces for e in f.edges} | {v for f in faces for v in f.verts})
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector(co), plane_no=Vector(no), clear_outer=True)
    if drop:
        bm.normal_update()
        dead = [f for f in bm.faces if drop(np.array(f.calc_center_median()), np.array(f.normal))]
        bmesh.ops.delete(bm, geom=dead, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    if smooth:
        inner = [v for v in bm.verts if not v.is_boundary]
        for _ in range(smooth):
            bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    _smooth_edges(bm, 4)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return o


def _smooth_edges(bm, iters):
    """Relax open edges along themselves, so a cut through a coarse mesh reads as a clean seam."""
    bverts = [v for v in bm.verts if v.is_boundary]
    for _ in range(iters):
        new = {}
        for v in bverts:
            nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            if len(nb) == 2:
                new[v] = v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25
        for v, c in new.items():
            v.co = c


def faces_mask_to_delete(info, vmask):
    return vmask


def remove_body_faces(info, vmask):
    """Delete body faces hidden under clothes (all their vertices covered)."""
    me = info.body.data
    bm = bmesh.new()
    bm.from_mesh(me)
    kill = [f for f in bm.faces if all(vmask[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(me)
    bm.free()


def remove_helpers(info, keep=('helper-upper-teeth', 'helper-lower-teeth', 'helper-tongue',
                               'helper-l-eyelashes-1', 'helper-l-eyelashes-2', 'helper-r-eyelashes-1', 'helper-r-eyelashes-2')):
    keepm = info.isbody.copy()
    for k in keep:
        keepm |= info.groups.get(k, np.zeros_like(keepm))
    me = info.body.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not keepm[v.index]], context='VERTS')
    bm.to_mesh(me)
    bm.free()


def copy_weights(obj, info, k=4):
    """Give a new mesh the bone weights of the nearest body vertices."""
    kd = kdtree.KDTree(int(info.isbody.sum()))
    idx = np.where(info.isbody)[0]
    for i in idx:
        kd.insert(Vector(info.co[i]), int(i))
    kd.balance()
    bones = [b.name for b in info.rig.data.bones]
    src = info.body.data.vertices
    names = [vg.name for vg in info.body.vertex_groups]
    for vg in list(obj.vertex_groups):
        obj.vertex_groups.remove(vg)
    vgs = {b: obj.vertex_groups.new(name=b) for b in bones}
    for v in obj.data.vertices:
        acc = {}
        hits = kd.find_n(obj.matrix_world @ v.co, k)
        tot = 0.0
        for co, i, d in hits:
            w = 1.0 / (d + 1e-4)
            tot += w
            for g in src[i].groups:
                nm = names[g.group]
                if nm in vgs:
                    acc[nm] = acc.get(nm, 0.0) + g.weight * w
        for nm, w in acc.items():
            if w / tot > 0.01:
                vgs[nm].add([v.index], w / tot, 'REPLACE')
    if not any(m.type == 'ARMATURE' for m in obj.modifiers):
        m = obj.modifiers.new('Armature', 'ARMATURE')
        m.object = info.rig


def front_profile(info, x=0.0, band=0.02):
    """Front-most body y for each height near the centre line (the character faces -y)."""
    m = info.isbody & (np.abs(info.co[:, 0] - x) < band)
    zs, ys = info.co[m, 2], info.co[m, 1]
    def at(z):
        sel = np.abs(zs - z) < 0.012
        return float(ys[sel].min()) if sel.any() else None
    return at


def make_tie(info, z_top, z_bot, name='Tie'):
    """A tie: knot, then a blade that widens to a point, a few mm in front of the shirt."""
    at = front_profile(info)
    rows = 40
    verts, faces, uvs = [], [], []
    cols = [-1.0, -0.5, 0.0, 0.5, 1.0]
    for r in range(rows + 1):
        t = r / rows
        z = z_top - (z_top - z_bot) * t
        y = at(z)
        y = (y if y is not None else -0.1) - 0.010 - 0.004 * math.sin(math.pi * min(1, t * 1.2))
        w = 0.013 + 0.03 * t ** 0.9
        for c in cols:
            tip = 0.0
            if t > 0.96:  # point
                tip = (t - 0.96) / 0.04 * 0.035 * (1 - abs(c))
            verts.append((c * w, y - 0.003 * (1 - c * c), z + tip))
            uvs.append(((c + 1) / 2, t * 2.5))
    nc = len(cols)
    for r in range(rows):
        for c in range(nc - 1):
            a = r * nc + c
            faces.append((a, a + 1, a + nc + 1, a + nc))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li in poly.loop_indices:
            uv.data[li].uv = uvs[me.loops[li].vertex_index]
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.parent = info.rig
    copy_weights(o, info)
    return o


def loosen(o, segs, smooth=0):
    """Push vertices out so they sit at least r(t) from a bone axis: trouser legs and sleeves hang
    as tubes instead of hugging the skin. segs: (head, tail, r_head, r_tail, select(co))."""
    me = o.data
    for v in me.vertices:
        c = np.array(v.co)
        best = None
        for a, b, r0, r1, sel in segs:
            if not sel(c):
                continue
            d = b - a
            t = np.clip((c - a) @ d / (d @ d), 0, 1)
            p = a + d * t
            r = np.linalg.norm(c - p)
            if best is None or r < best[0]:
                best = (r, p, r0 + (r1 - r0) * t)
        if best is None:
            continue
        r, p, rmin = best
        if 1e-6 < r < rmin:
            v.co = Vector(p + (c - p) * (1 + (rmin / r - 1) * 0.9))
    if smooth:
        bm = bmesh.new(); bm.from_mesh(me)
        inner = [v for v in bm.verts if not v.is_boundary]
        for _ in range(smooth):
            bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bm.to_mesh(me); bm.free()


def drape(o, info, offset, iters=12, region=None, factor=0.6):
    """Relax a garment like cloth: smooth it, then push back out anything that sinks closer than
    offset to the skin. Bridges over hollows (between the breasts, the sternum, abs) instead of
    following every contour."""
    idx = np.where(info.isbody)[0]
    if not hasattr(info, '_kd'):
        kd = kdtree.KDTree(len(idx))
        for i in idx:
            kd.insert(Vector(info.co[i]), int(i))
        kd.balance()
        info._kd = kd
    kd = info._kd
    bm = bmesh.new()
    bm.from_mesh(o.data)
    vs = [v for v in bm.verts if not v.is_boundary and (region is None or region(np.array(v.co)))]
    for _ in range(iters):
        bmesh.ops.smooth_vert(bm, verts=vs, factor=factor, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        for v in vs:
            q, i, d = kd.find(v.co)
            n = Vector(info.no[i])
            h = (v.co - q).dot(n)
            if h < offset:
                v.co += n * (offset - h)
    bm.to_mesh(o.data)
    bm.free()


def hang(o, region, reach=0.14, slope=0.12):
    """Let the front fall from the fullest point above instead of tucking under it: each vertex is
    pulled forward to the cloth line hanging from the vertices up to reach above it."""
    co = np.array([v.co[:] for v in o.data.vertices])
    sel = np.array([region(c) for c in co])
    idx = np.where(sel)[0]
    if not len(idx):
        return
    P = co[idx]
    dx = np.abs(P[:, None, 0] - P[None, :, 0]) < 0.012
    dz = P[None, :, 2] - P[:, None, 2]
    ok = dx & (dz > 0) & (dz < reach)
    line = np.where(ok, P[None, :, 1] + slope * dz, np.inf).min(1)
    newy = np.minimum(P[:, 1], line)
    for k, i in enumerate(idx):
        o.data.vertices[i].co.y = newy[k]


def lapels_from(jacket, planes, lift=0.004):
    """The lapels: a band of the jacket front next to the V, copied and lifted a few mm."""
    o = jacket.copy()
    o.data = jacket.data.copy()
    o.name = o.data.name = 'Lapels'
    bpy.context.collection.objects.link(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for co, no, region in planes:
        faces = [f for f in bm.faces if region is None or region(np.array(f.calc_center_median()))]
        geom = list(set(faces) | {e for f in faces for e in f.edges} | {v for f in faces for v in f.verts})
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector(co), plane_no=Vector(no), clear_outer=True)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * lift
    bm.to_mesh(o.data)
    bm.free()
    return o


def finish(o, thickness, levels=1, crease=0.0):
    """Give a garment shell real cloth thickness and round it off: solidify inwards with closed rims,
    then Catmull-Clark subdivision, applied into the mesh (vertex groups carry through)."""
    bm = bmesh.new(); bm.from_mesh(o.data)          # no slivers: they make solidify spike
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0015)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=0.0005)
    bm.to_mesh(o.data); bm.free()
    arm = [m for m in o.modifiers if m.type == 'ARMATURE']
    for m in arm:
        m.show_viewport = False
    sol = o.modifiers.new('Solid', 'SOLIDIFY')
    sol.thickness = thickness
    sol.offset = -1.0
    sol.use_rim = True
    sol.use_even_offset = False
    sol.use_quality_normals = True
    sol.edge_crease_rim = crease
    if levels:
        sub = o.modifiers.new('Sub', 'SUBSURF')
        sub.levels = sub.render_levels = levels
        sub.boundary_smooth = 'PRESERVE_CORNERS'
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    bm.from_object(o, dg)            # evaluated geometry, with UVs and vertex groups
    for m in list(o.modifiers):
        if m.type != 'ARMATURE':
            o.modifiers.remove(m)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    for m in arm:
        m.show_viewport = True
    return o


def make_button(info, z, y_off=0.0, r=0.0085, name='Button'):
    """A flat, slightly domed button on the jacket front at height z."""
    at = front_profile(info, band=0.03)
    yf = (at(z) or -0.12) - 0.016 - y_off
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=20, radius1=r, radius2=r * 0.85, depth=0.003)
    for v in bm.verts:
        v.co = Vector((v.co.x, -v.co.z, v.co.y)) + Vector((0, yf, z))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    uv = me.uv_layers.new(name='UVMap')
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.parent = info.rig
    copy_weights(o, info)
    return o


class FrontSurface:
    """y of the (smoothed) body front at any (x, z): nearest front vertices in the xz plane."""
    def __init__(self, info, co=None):
        co = info.co if co is None else co
        m = info.isbody & (info.no[:, 1] < -0.2)
        self.idx = np.where(m)[0]
        self.co = co
        self.kd = kdtree.KDTree(len(self.idx))
        for j, i in enumerate(self.idx):
            self.kd.insert(Vector((co[i, 0], co[i, 2], 0)), j)
        self.kd.balance()

    def y(self, x, z):
        hits = self.kd.find_n(Vector((x, z, 0)), 4)
        w = np.array([1 / (d + 1e-3) for _, _, d in hits])
        ys = np.array([self.co[self.idx[j], 1] for _, j, _ in hits])
        return float((w * ys).sum() / w.sum())


def _grid_object(name, verts, faces, uvs, info):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li in poly.loop_indices:
            uv.data[li].uv = uvs[me.loops[li].vertex_index]
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.parent = info.rig
    copy_weights(o, info)
    return o


def collar_points(info, front, z_neck, name='CollarPoints'):
    """The two pointed flaps of a dress-shirt collar, lying on the chest and over the sides of the knot."""
    verts, faces, uvs = [], [], []
    n = 10
    for side in (1, -1):
        A = np.array([0.006, z_neck + 0.014]); B = np.array([0.052, z_neck + 0.004])     # top edge (fold)
        D = np.array([0.008, z_neck - 0.022]); C = np.array([0.040, z_neck - 0.068])     # inner edge down to the point
        base = len(verts)
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = i / n, j / n
                p = (A * (1 - u) + B * u) * (1 - v) + (D * (1 - u) + C * u) * v
                x, z = p
                lift = 0.016 - 0.011 * min(1, max(0, (x - 0.012) / 0.03)) + 0.003 * (1 - v)
                verts.append((side * x, front.y(side * x, z) - lift, z))
                uvs.append((u, v))
        for i in range(n):
            for j in range(n):
                a = base + i * (n + 1) + j
                q = (a, a + 1, a + n + 2, a + n + 1)
                faces.append(q if side > 0 else q[::-1])
    return _grid_object(name, verts, faces, uvs, info)


def make_knot(info, front, z_neck, name='Knot'):
    """A four-in-hand knot: a tapered, rounded block in the collar opening."""
    zt, zb = z_neck + 0.016, z_neck - 0.024
    yb = front.y(0, (zt + zb) / 2)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        t = v.co.z + 0.5                      # 0 bottom .. 1 top
        w = 0.013 + 0.008 * t
        d = 0.009 + 0.002 * t
        v.co = Vector((v.co.x * 2 * w, yb - 0.009 - 0.0 + v.co.y * 2 * d - 0.004 * t, zb + (zt - zb) * t))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    me.uv_layers.new(name='UVMap')
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.parent = info.rig
    sub = o.modifiers.new('Sub', 'SUBSURF'); sub.levels = 3
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new(); bm.from_object(o, dg); o.modifiers.remove(sub); bm.to_mesh(o.data); bm.free()
    copy_weights(o, info)
    return o


def surface_patch(target, name, corners, lift, info, n=8):
    """A small panel lying on the front of target (rays cast from the front): corners are
    (x, z) for top-left, top-right, bottom-right, bottom-left."""
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons([v.co.copy() for v in target.data.vertices], [p.vertices[:] for p in target.data.polygons])
    A, B, C, D = [np.array(c, float) for c in corners]
    verts, faces, uvs = [], [], []
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = i / n, j / n
            x, z = (A * (1 - u) + B * u) * (1 - v) + (D * (1 - u) + C * u) * v
            hit = bvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)), 2.0)
            y = hit[0].y if hit[0] is not None else -0.12
            nrm = hit[1] if hit[0] is not None else Vector((0, -1, 0))
            p = Vector((x, y, z)) + nrm * lift
            verts.append(tuple(p)); uvs.append((u, v))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + 1, a + n + 2, a + n + 1))
    return _grid_object(name, verts, faces, uvs, info)


def weights_from(obj, src, k=3):
    """Give obj the bone weights of the nearest vertices of src, so a patch moves with the cloth under it."""
    co = [v.co.copy() for v in src.data.vertices]
    kd = kdtree.KDTree(len(co))
    for i, c in enumerate(co):
        kd.insert(c, i)
    kd.balance()
    names = [vg.name for vg in src.vertex_groups]
    for vg in list(obj.vertex_groups):
        obj.vertex_groups.remove(vg)
    vgs = {}
    for v in obj.data.vertices:
        acc, tot = {}, 0.0
        for c, i, d in kd.find_n(v.co, k):
            w = 1.0 / (d + 1e-4)
            tot += w
            for g in src.data.vertices[i].groups:
                acc[names[g.group]] = acc.get(names[g.group], 0.0) + g.weight * w
        for nm, w in acc.items():
            if w / tot > 0.01:
                if nm not in vgs:
                    vgs[nm] = obj.vertex_groups.new(name=nm)
                vgs[nm].add([v.index], w / tot, 'REPLACE')


def pockets(jacket, info, style, z_hem, z_btn):
    """Flap pockets at the hips and, for the host, a breast-pocket welt with a folded white square."""
    out = {}
    zf = z_hem + 0.085
    co = np.array([v.co[:] for v in jacket.data.vertices])
    row = co[(np.abs(co[:, 2] - zf) < 0.015) & (co[:, 1] < 0)]
    half = np.abs(row[:, 0]).max() if len(row) else 0.18
    flaps = []
    for s in (1, -1):
        x0, x1 = s * 0.38 * half, s * 0.82 * half
        flaps.append(surface_patch(jacket, 'Flap', [(x0, zf), (x1, zf), (x1 * 0.99, zf - 0.05), (x0, zf - 0.05)], 0.0025, info))
    out['Flaps'] = _join(flaps, 'Flaps')
    if style == 'host':
        zb = z_btn + 0.2
        x0, x1 = 0.105, 0.18
        out['Welt'] = surface_patch(jacket, 'Welt', [(x0, zb + 0.01), (x1, zb + 0.016), (x1, zb), (x0, zb - 0.006)], 0.0025, info, 6)
        sq = surface_patch(jacket, 'PocketSquare', [(x0 + 0.012, zb + 0.032), (x1 - 0.02, zb + 0.04), (x1 - 0.02, zb + 0.012), (x0 + 0.012, zb + 0.006)], 0.0015, info, 6)
        for v in sq.data.vertices:          # two soft peaks
            u = (v.co.x - x0) / (x1 - x0)
            v.co.z += 0.008 * max(0.0, math.sin(u * 2 * math.pi)) * (v.co.z > zb + 0.012)
        out['PocketSquare'] = sq
    for o in out.values():
        weights_from(o, jacket)
    return out


def _join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = o.data.name = name
    return o


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def suit(info, style):
    """Shirt, collar, jacket with lapels, trousers, belt, shoes, and a tie for the host.
    Returns ({name: object}, vertex mask of body skin that is now hidden)."""
    co, z = info.co, info.co[:, 2]
    x, y = co[:, 0], co[:, 1]
    isb = info.isbody
    inset = lambda bones: np.isin(info.dom, list(bones))
    z_neck = info.z('neck_01') + 0.005
    z_waist = info.z('pelvis') + 0.035
    z_hem = info.z('pelvis') - 0.15
    z_ankle = info.z('calf_l', 1) + 0.035
    z_btn = info.z('spine_02') - 0.01 if style == 'host' else info.z('spine_02') + 0.02
    out = {}

    def wrist_plane(side, at):
        h, t = info.j['lowerarm_' + side]
        d = _unit(t - h)
        p = h + (t - h) * at
        return (p, d, lambda c, p=p: np.linalg.norm(c - p) < 0.14)

    def v_planes(width0, slope, z0, ztop, dx=0.0):
        """The V opening: two planes through lines x = +-(width0 + slope (z - z0)), front only, above z0."""
        ps = []
        for sgn in (1, -1):
            n = _unit((-sgn, 0, slope))      # removes the inside of the V
            p = (sgn * (width0 + dx), 0, z0)
            ps.append((p, n, lambda c, sgn=sgn: c[1] < -0.03 and c[2] > z0 - 0.005 and c[2] < ztop and sgn * c[0] > -0.004))
        return ps

    upper = isb & inset(TORSO | ARMS | {'neck_01', 'hand_l', 'hand_r'})
    shirt_planes = [((0, 0, z_waist - 0.05), (0, 0, -1), None), ((0, 0, z_neck + 0.004), (0, 0, 1), lambda c: c[2] > z_neck - 0.06),
                    wrist_plane('l', 1.0), wrist_plane('r', 1.0)]
    if style != 'host':   # open, rounded neckline on the blouse: one plane tilted down at the front
        shirt_planes[1] = ((0, -0.1, z_neck - 0.08), _unit((0, -0.85, 1)), None)
    sm = info.smoothed(40)
    out['Shirt'] = cut(info, 'Shirt', upper, 0.003, smooth=2, planes=shirt_planes, subdiv=1, base=sm)

    if style == 'host':
        collar_m = isb & inset({'neck_01', 'spine_03', 'clavicle_l', 'clavicle_r'})
        tilt = _unit((0, -0.45, 1))
        out['Collar'] = cut(info, 'Collar', collar_m, 0.0075, smooth=2, subdiv=1, planes=[
            ((0, 0, z_neck - 0.012), (0, 0, -1), None),
            ((0, 0, z_neck + 0.03), tilt, None),
            ((0.004, -0.05, 0), _unit((-1, 0, -0.25)), lambda c: c[1] < -0.02 and c[0] > -0.001),
            ((-0.004, -0.05, 0), _unit((1, 0, -0.25)), lambda c: c[1] < -0.02 and c[0] < 0.001)])

    # jacket: open in a V above the button, cut away below it, sleeves a little shorter than the shirt
    slope = 0.2 if style == 'host' else 0.3
    jm = isb & inset(TORSO | ARMS | LEGS - {'calf_l', 'calf_r'} | {'neck_01'})
    cutaway = []
    for sgn in (1, -1):
        n = _unit((-sgn, 0, -0.25))
        cutaway.append(((sgn * 0.008, 0, z_btn), n, lambda c, sgn=sgn: c[1] < -0.02 and c[2] < z_btn + 0.005 and sgn * c[0] > -0.004))
    jplanes = ([((0, 0, z_hem), (0, 0, -1), None),
                ((0, 0, z_neck + 0.012), _unit((0, -0.3, 1)), lambda c: c[2] > z_neck - 0.08),
                wrist_plane('l', 0.95), wrist_plane('r', 0.95)]
               + v_planes(0.008, slope, z_btn, z_neck + 0.08) + cutaway)
    under = lambda c, n: abs(c[0]) < 0.075 and c[2] < info.z('pelvis') + 0.02 and n[2] < -0.3
    out['Jacket'] = cut(info, 'Jacket', jm, 0.013, smooth=4, planes=jplanes, drop=under, subdiv=0, base=sm)
    # relax the front like cloth (bridges the chest instead of moulding to it), then clear the belt
    front_chest = lambda c: c[1] < -0.02 and z_waist - 0.03 < c[2] < z_neck - 0.02
    hang(out['Jacket'], lambda c: c[1] < -0.03 and z_waist - 0.08 < c[2] < z_neck - 0.04)
    drape(out['Jacket'], info, 0.012, 10, front_chest, 0.5)
    drape(out['Jacket'], info, 0.019, 1, lambda c: z_waist - 0.06 < c[2] < z_waist + 0.03, 0.0)
    drape(out['Shirt'], info, 0.0025, 2, front_chest, 0.5)
    # lapels: a band just outside the V, a few mm proud of the jacket
    lap = v_planes(0.008, slope, z_btn + 0.015, z_neck + 0.08)
    outer = []
    for sgn in (1, -1):
        n = _unit((sgn, 0, -slope * 1.25))
        outer.append(((sgn * (0.058 if style == 'host' else 0.045), 0, z_btn), n, lambda c, sgn=sgn: sgn * c[0] > -0.004))
    out['Lapels'] = lapels_from(out['Jacket'], [((0, 0, z_btn + 0.015), (0, 0, -1), None), ((0, 0, z_neck - 0.005), _unit((0, -0.3, 1)), None),
                                                ((0, -0.045, 0), (0, 1, 0), None)] + lap + outer)
    chest = lambda c: z_waist - 0.03 < c[2] < z_neck - 0.015
    drape(out['Shirt'], info, 0.002, 1, chest, 0.0)
    lm = isb & inset(LEGS)
    out['Trousers'] = cut(info, 'Trousers', lm, 0.009, smooth=4, subdiv=0, base=sm, planes=[
        ((0, 0, z_waist), (0, 0, 1), None), ((0, 0, z_ankle), (0, 0, -1), None)])
    J = info.j
    legs = []
    for sd, sgn in (('l', 1), ('r', -1)):
        legs.append((J['thigh_' + sd][0] + np.array([0, 0, -0.06]), J['calf_' + sd][1], 0.085, 0.068, lambda c, sgn=sgn: sgn * c[0] > 0))
    loosen(out['Trousers'], legs, smooth=3)
    arms = []
    for sd, sgn in (('l', 1), ('r', -1)):
        arms.append((J['upperarm_' + sd][0], J['upperarm_' + sd][1], 0.058, 0.05, lambda c, sgn=sgn, sd=sd: sgn * c[0] > abs(J['upperarm_' + sd][0][0]) + 0.02))
        arms.append((J['lowerarm_' + sd][0], J['lowerarm_' + sd][1], 0.05, 0.044, lambda c, sgn=sgn: sgn * c[0] > 0.2))
    loosen(out['Jacket'], arms, smooth=2)
    out['Belt'] = cut(info, 'Belt', isb & inset(LEGS | TORSO), 0.0115, smooth=1, planes=[
        ((0, 0, z_waist + 0.002), (0, 0, 1), None), ((0, 0, z_waist - 0.033), (0, 0, -1), None)])
    fm = isb & inset(FEET | {'calf_l', 'calf_r'})
    out['Shoes'] = cut(info, 'Shoes', fm, 0.009, smooth=6, subdiv=1, planes=[((0, 0, z_ankle + 0.012), (0, 0, 1), None)])
    feet = []
    for sd, sgn in (('l', 1), ('r', -1)):
        a = J['foot_' + sd][0] + np.array([0, 0.03, -0.035]); b = J['ball_' + sd][1] + np.array([0, -0.01, -0.005])
        feet.append((a, b, 0.05, 0.032, lambda c, sgn=sgn: sgn * c[0] > 0))
    loosen(out['Shoes'], feet, smooth=8)
    for v in out['Shoes'].data.vertices:   # flat sole
        if v.co[2] < 0.012: v.co[2] = max(0.0, v.co[2] * 0.3)
    if style == 'host':
        front = FrontSurface(info, sm[0])
        out['Tie'] = make_tie(info, z_neck - 0.012, z_waist + 0.015)
        out['Knot'] = make_knot(info, front, z_neck)
        out['CollarPoints'] = collar_points(info, front, z_neck)
    out['Button'] = make_button(info, z_btn - 0.005)
    out.update(pockets(out['Jacket'], info, style, z_hem, z_btn))
    weights_from(out['Button'], out['Jacket'])

    # skin that is now hidden, kept a little inside the garment edges so no gap shows
    a_l, a_r = info.along('lowerarm_l'), info.along('lowerarm_r')
    arm_cov = inset(ARMS) & ~(inset({'lowerarm_l', 'lowerarm_r'}) & (np.where(x > 0, a_l, a_r) > 0.85))
    neckline = (y < -0.02) & (z > info.z('spine_03', 1)) if style != 'host' else np.zeros_like(isb)
    covered = isb & ((inset(TORSO) & (z > z_waist - 0.02) & (z < z_neck - 0.02) & ~neckline) | arm_cov
                     | (inset(LEGS) & (z > z_ankle + 0.03)) | (inset(FEET)))
    return out, covered
