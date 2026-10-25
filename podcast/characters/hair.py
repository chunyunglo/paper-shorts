"""Hair grown in code: a painted cap on the scalp plus a few thousand strand cards.

Each card is rooted on the scalp, follows a combing direction (away from the parting, then
falling with gravity) and is kept just outside the head. The cards carry an alpha texture of
thin strands, so up close it reads as hair rather than a helmet.
"""
import math
import bpy, bmesh
import numpy as np
from mathutils import Vector, kdtree


def strand_texture(color, w=256, h=1024, seed=3):
    rng = np.random.default_rng(seed)
    alpha = np.zeros((h, w), np.float32)
    shade = np.ones((h, w), np.float32)
    v = np.linspace(0, 1, h)[:, None]
    for _ in range(int(w * 2.2)):
        x = rng.uniform(0, w)
        sw = rng.uniform(1.0, 2.2)
        end = rng.uniform(0.7, 1.0)
        wig = np.sin(v[:, 0] * rng.uniform(2, 6) + rng.uniform(0, 6)) * rng.uniform(0.5, 2.5)
        xs = np.arange(w)[None, :]
        prof = np.exp(-((xs - (x + wig[:, None])) / sw) ** 2)
        prof *= (v < end) * np.clip((end - v) / 0.08, 0, 1)
        alpha = np.maximum(alpha, prof * rng.uniform(0.7, 1.0))
        shade = np.where(prof > 0.5, rng.uniform(0.75, 1.25), shade)
    alpha = np.clip(alpha * 2.0, 0, 1)
    c = np.array(color, np.float32)
    rgb = c[None, None] * shade[..., None] * (0.85 + 0.15 * (1 - v[..., None]))  # roots slightly darker
    rgb *= (0.8 + 0.2 * v[..., None])
    return np.clip(rgb, 0, 1), alpha


class Head:
    def __init__(self, body, head_mask):
        me = body.data
        co = np.array([v.co[:] for v in me.vertices])
        no = np.array([v.normal[:] for v in me.vertices])
        idx = np.where(head_mask)[0]
        self.co, self.no = co, no
        self.kd = kdtree.KDTree(len(idx))
        for i in idx:
            self.kd.insert(Vector(co[i]), int(i))
        self.kd.balance()

    def nearest(self, p):
        q, i, d = self.kd.find(Vector(p))
        return np.array(q), self.no[i], d


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def roots_on(body, scalp_mask, count, seed):
    """Area-weighted random points on scalp faces: (points, normals)."""
    me = body.data
    me.calc_loop_triangles()
    co = np.array([v.co[:] for v in me.vertices])
    tris, areas = [], []
    for t in me.loop_triangles:
        vi = list(t.vertices)
        if all(scalp_mask[i] for i in vi):
            a, b, c = co[vi]
            tris.append(vi)
            areas.append(np.linalg.norm(np.cross(b - a, c - a)) / 2)
    tris, areas = np.array(tris), np.array(areas)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(tris), size=count, p=areas / areas.sum())
    r1, r2 = rng.random(count), rng.random(count)
    s = np.sqrt(r1)
    w = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    pts = np.einsum('ni,nij->nj', w, co[tris[pick]])
    a, b, c = co[tris[pick][:, 0]], co[tris[pick][:, 1]], co[tris[pick][:, 2]]
    nrm = np.cross(b - a, c - a)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    return pts, nrm


def grow(body, rig, scalp_mask, head_mask, style, head_c):
    """Build the cap and the cards; returns the hair object (weighted to the head bone)."""
    H = Head(body, head_mask)
    rng = np.random.default_rng(style.get('seed', 1))
    pts, nrm = roots_on(body, scalp_mask, style['cards'], style.get('seed', 1))
    verts, faces, uvs = [], [], []
    part = style.get('part_x', 0.0)
    for k in range(len(pts)):
        p0, n0 = pts[k], nrm[k]
        rel = p0 - head_c
        # length by region: top / front fringe / sides / back
        front = np.clip((-rel[1] - 0.02) / 0.06, 0, 1)
        top = np.clip((rel[2] - 0.04) / 0.05, 0, 1)
        L = style['side_len'] + (style['top_len'] - style['side_len']) * top
        L += style.get('fringe_len', 0) * front * top
        L *= rng.uniform(0.75, 1.1)
        # combing direction in the tangent plane
        side = 1.0 if rel[0] > part else -1.0
        comb = np.array([side * style.get('sideways', 0.6), style.get('backward', 0.5), 0.0])
        comb = comb * top + np.array([0, 0.15, -1.0]) * (1 - top)
        if style.get('fringe_dir') is not None:
            fd = np.array(style['fringe_dir'], float)
            comb = comb * (1 - front * top) + fd * front * top
        d = _unit(comb - n0 * (comb @ n0))
        segs = style.get('segs', 6)
        step = L / segs
        p = p0 + n0 * 0.001
        chain = [p.copy()]
        for s in range(1, segs + 1):
            t = s / segs
            d = d + np.array([0, 0, -style.get('gravity', 0.2)]) * t
            q, nq, dist = H.nearest(p)
            d = _unit(d - nq * (d @ nq) * (1 - t * 0.6))
            p = p + d * step
            lift = style.get('volume', 0.006) * (0.4 + t) + rng.uniform(0, 0.003)
            q, nq, _ = H.nearest(p)
            h = (p - q) @ nq
            if h < lift:
                p = p + nq * (lift - h)
            # keep the face clear: hair in front of the face is tucked beside it
            fz, fx = style.get('face_top', None), style.get('face_half', 0.075)
            if fz is not None:
                r = p - head_c
                if r[2] < fz and r[1] < -0.02 and abs(r[0]) < fx:
                    p[0] = head_c[0] + np.sign(r[0] if abs(r[0]) > 1e-4 else side) * (fx + rng.uniform(0, 0.006))
                    d = _unit(d + np.array([np.sign(r[0] or side) * 0.6, 0.3, 0]))
            chain.append(p.copy())
        w = style['width'] * rng.uniform(0.8, 1.2)
        base = len(verts)
        for s, c in enumerate(chain):
            t = s / segs
            q, nq, _ = H.nearest(c)
            dd = _unit(chain[min(s + 1, segs)] - chain[max(s - 1, 0)])
            x = _unit(np.cross(dd, nq)) * w * (1 - 0.55 * t) / 2
            verts += [tuple(c - x), tuple(c + x)]
            u0 = rng.random() * 0.6
            uvs += [(u0, 1 - t), (u0 + 0.4, 1 - t)]
        for s in range(segs):
            a = base + 2 * s
            faces.append((a, a + 1, a + 3, a + 2))
    me = bpy.data.meshes.new('Hair')
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[me.loops[li].vertex_index]
    for poly in me.polygons:
        poly.use_smooth = True
    o = bpy.data.objects.new('Hair', me)
    bpy.context.collection.objects.link(o)
    vg = o.vertex_groups.new(name='head')
    vg.add(list(range(len(verts))), 1.0, 'REPLACE')
    m = o.modifiers.new('Armature', 'ARMATURE')
    m.object = rig
    return o


def cap(body, rig, scalp_mask, offset=0.0025, name='HairCap'):
    """The scalp faces copied a little outward; textured as dense hair so no skin shows through."""
    o = body.copy()
    o.data = body.data.copy()
    o.name = o.data.name = name
    bpy.context.collection.objects.link(o)
    if o.data.shape_keys:
        o.shape_key_clear()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    for v in bm.verts:
        v.co = v.co + v.normal * offset
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not all(scalp_mask[v.index] for v in f.verts)], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(o.data)
    bm.free()
    for vg in list(o.vertex_groups):
        if vg.name != 'head':
            o.vertex_groups.remove(vg)
    vg = o.vertex_groups.get('head') or o.vertex_groups.new(name='head')
    vg.add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')
    return o


def bob(body, rig, head_c, eye_z, style, name='HairBob'):
    """A sculpted bob: a shell around the skull that drops straight down past the ears to the
    jaw, open over the face, with a side-swept fringe. Textured with long strands (opaque)."""
    from mathutils.bvhtree import BVHTree
    me = body.data
    co = [v.co for v in me.vertices]
    bvh = BVHTree.FromPolygons(co, [p.vertices for p in me.polygons])
    c = Vector(head_c)
    nt, nf = style.get('n_theta', 120), style.get('n_phi', 60)
    z_bot = eye_z + style.get('bottom', -0.095)      # where the bob ends (around the jaw)
    z_drop = eye_z + (style.get('drop') or 0.0)      # below this the hair falls straight (bob only)
    part = style.get('part_theta', 0.35)             # parting angle (rad, + = character's left)
    grid = {}
    verts, uvs = [], []
    rng = np.random.default_rng(style.get('seed', 3))
    tip = np.array([rng.uniform(-0.012, 0.004) for _ in range(nt)])
    for i in range(nt):
        th = 2 * math.pi * i / nt - math.pi       # 0 = front (-y), +-pi = back
        dxy = Vector((math.sin(th), -math.cos(th), 0))
        prev = None
        for j in range(nf + 1):
            ph = math.radians(88) - math.radians(178) * j / nf   # from the crown down
            d = (dxy * math.cos(ph) + Vector((0, 0, math.sin(ph)))).normalized()
            hit = bvh.ray_cast(c, d, 0.3)      # from inside the skull: first surface is head/jaw/neck, never the shoulder
            if hit[0] is None:
                continue
            p = hit[0]
            front = math.cos(th)
            thick = style.get('thick_top', 0.012) + (style.get('thick_side', 0.02) - style.get('thick_top', 0.012)) * (1 - max(0.0, math.sin(ph)))
            if front > 0:   # thin out towards the front hairline so the edge meets the forehead
                edge = (p.z - (eye_z + style.get('open_top', 0.06))) / 0.035
                thick *= min(1.0, max(0.12, edge)) ** (front * 1.5)
            q = p + d * thick
            if style.get('drop') is not None and q.z < z_drop and prev is not None:
                # fall straight down from where it left the head, with a soft inward curve at the ends
                q = Vector((prev.x, prev.y, q.z))
            zb = z_bot
            if style.get('bottom_back') is not None:   # short cut: above the ears at the sides, down to the nape at the back
                bb = eye_z + style['bottom_back']
                zb = z_bot + (bb - z_bot) * max(0.0, -math.cos(th)) ** 1.5
            if q.z < zb + tip[i] * style.get('tip_scale', 1.0):
                break
            # face opening: below a hairline that sweeps down from the forehead to behind the temples
            ath = abs(th)
            zcut = eye_z + style.get('open_top', 0.06) - max(0.0, (ath - 0.6) / 0.75) * 0.3
            if ath < 1.35 and q.z < zcut:
                break
            prev = q.copy() if q.z >= z_drop else prev
            grid[(i, j)] = len(verts)
            verts.append(tuple(q))
            uvs.append(((i / nt) * style.get('u_rep', 6), 1 - (j / nf)))
    faces = []
    for i in range(nt):
        for j in range(nf):
            a, b2, c2, d2 = (i, j), ((i + 1) % nt, j), ((i + 1) % nt, j + 1), (i, j + 1)
            if all(k in grid for k in (a, b2, c2, d2)):
                faces.append((grid[a], grid[d2], grid[c2], grid[b2]))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    uvl = mesh.uv_layers.new(name='UVMap')
    for poly in mesh.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[mesh.loops[li].vertex_index]
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    vg = o.vertex_groups.new(name='head')
    vg.add(list(range(len(verts))), 1.0, 'REPLACE')
    m = o.modifiers.new('Armature', 'ARMATURE')
    m.object = rig
    return o


def long_strands(color, w=512, h=1024, seed=7):
    """Opaque texture for sculpted hair: fine strands running along v, darker at the roots,
    alpha only at the tips so the ends look uneven."""
    rng = np.random.default_rng(seed)
    x = np.arange(w)
    base = np.zeros(w)
    for _ in range(400):
        base += rng.uniform(0.2, 1.0) * np.exp(-((x - rng.uniform(0, w)) / rng.uniform(0.8, 3)) ** 2)
    base = (base - base.min()) / (base.max() - base.min() + 1e-9)
    v = np.linspace(0, 1, h)[:, None]
    wav = np.sin(v * 9 + np.linspace(0, 6, w)[None, :] * 0.3) * 0.02
    shade = 0.45 + 0.9 * base[None, :] + wav
    c = np.array(color, np.float32)
    rgb = c[None, None] * shade[..., None] * (0.8 + 0.25 * v[..., None])
    # uneven tips: each column ends at its own length
    ends = 0.04 + 0.07 * rng.random(w)
    alpha = np.clip(((1 - v) - (ends[None, :] - 0.04)) / 0.03, 0, 1)
    alpha = alpha[::-1] if False else alpha
    return np.clip(rgb, 0, 1), alpha
