"""Skin, face and fabric textures painted in code.

The skin is painted in 3D: every texel of the body's UV map is rasterised to the rest position it
covers, so freckles, blush, lips, brows and stubble are placed by where they are on the head rather
than by hand in UV space.
"""
import gzip, math
import bpy, bmesh
import numpy as np
from mathutils import Vector


# ---------- noise ----------
def _hash3(ix, iy, iz, seed):
    h = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0xFFFFFF)


def vnoise(p, freq, seed=0):
    """Smooth value noise on 3D points p (N,3) at frequency freq (cycles per metre), range 0..1."""
    q = p * freq
    i = np.floor(q).astype(np.int64)
    f = q - i
    u = f * f * (3 - 2 * f)
    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (u[:, 0] if dx else 1 - u[:, 0]) * (u[:, 1] if dy else 1 - u[:, 1]) * (u[:, 2] if dz else 1 - u[:, 2])
                out = out + w * _hash3(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return out


def fbm(p, freq, oct=4, seed=0):
    s, a, n = 0.0, 0.5, 0.0
    for k in range(oct):
        s = s + a * vnoise(p, freq * 2 ** k, seed + k)
        n += a
        a *= 0.5
    return s / n


# ---------- rasteriser ----------
def rasterise(obj, size, attrs, mat_index=None):
    """Return (mask, pos, {name: map}) where every covered texel holds the interpolated rest
    position and per-vertex attributes. attrs: {name: array (n_verts,)}."""
    me = obj.data
    me.calc_loop_triangles()
    uv = me.uv_layers.active.data
    co = np.array([v.co[:] for v in me.vertices])
    mask = np.zeros((size, size), bool)
    pos = np.zeros((size, size, 3), np.float32)
    maps = {k: np.zeros((size, size), np.float32) for k in attrs}
    for tri in me.loop_triangles:
        if mat_index is not None and tri.material_index != mat_index:
            continue
        vi = list(tri.vertices)
        t = np.array([uv[l].uv[:] for l in tri.loops]) * size
        t[:, 1] = size - t[:, 1]
        x0, y0 = np.floor(t.min(0)).astype(int)
        x1, y1 = np.ceil(t.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = t
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
        if not inside.any():
            continue
        Y, X = np.nonzero(inside)
        Y, X = Y + y0, X + x0
        W = np.stack([w0[inside], w1[inside], w2[inside]], 1)
        pos[Y, X] = W @ co[vi]
        mask[Y, X] = True
        for k, arr in attrs.items():
            maps[k][Y, X] = W @ arr[vi]
    return mask, pos, maps


def dilate(img, mask, n=8):
    """Bleed colours past UV island edges so mip-mapping does not pull in black seams."""
    img = img.copy()
    m = mask.copy()
    for _ in range(n):
        acc = np.zeros_like(img)
        cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sm = np.roll(m, (dy, dx), (0, 1))
            acc += np.roll(img, (dy, dx), (0, 1)) * sm[..., None]
            cnt += sm
        grow = (~m) & (cnt > 0)
        img[grow] = acc[grow] / cnt[grow][:, None]
        m = m | grow
    return img


def save_png(name, rgb, path):
    from PIL import Image  # noqa
    raise NotImplementedError


def to_image(name, arr, path, alpha=None):
    """Write an array (H,W,3) in 0..1 (sRGB) to a Blender image packed into the .blend."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=alpha is not None)
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = np.clip(arr, 0, 1)
    if alpha is not None:
        rgba[..., 3] = np.clip(alpha, 0, 1)
    img.pixels.foreach_set(rgba[::-1].ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    return img


# ---------- vertex tags (must run before the body is cut) ----------
def tag_vertices(body, mpfb_targets):
    """Store brow position as a vertex attribute, from the MakeHuman eyebrow target."""
    n = len(body.data.vertices)
    brow = np.zeros(n, np.float32)
    with gzip.open(f"{mpfb_targets}/eyebrows/eyebrows-trans-up.target.gz", 'rt') as f:
        for line in f:
            p = line.split()
            if len(p) == 4 and p[0].isdigit():
                i = int(p[0])
                if i < n:
                    brow[i] = math.sqrt(sum(float(x) ** 2 for x in p[1:]))
    brow /= brow.max() or 1
    a = body.data.attributes.new('brow', 'FLOAT', 'POINT')
    a.data.foreach_set('value', brow)


def _group_weights(obj, name):
    n = len(obj.data.vertices)
    w = np.zeros(n, np.float32)
    vg = obj.vertex_groups.get(name)
    if vg is None:
        return w
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                w[v.index] = g.weight
    return w


def paint_skin(body, spec, outdir, size=4096):
    S = spec['skin']
    me = body.data
    brow = np.zeros(len(me.vertices), np.float32)
    me.attributes['brow'].data.foreach_get('value', brow)
    attrs = {'brow': brow, 'lips': _group_weights(body, 'lips'), 'nails': np.maximum(_group_weights(body, 'fingernails'), _group_weights(body, 'toenails')),
             'scalp': np.asarray(spec['_scalp'], np.float32), 'ears': _group_weights(body, 'ears'),
             'rim': np.asarray(spec.get('_rim', np.zeros(len(me.vertices))), np.float32),
             'nz': np.array([v.normal.z for v in me.vertices], np.float32),
             'ny': np.array([v.normal.y for v in me.vertices], np.float32)}
    mask, P, M = rasterise(body, size, attrs, mat_index=0)
    p = P[mask]
    head = np.array(spec['_head'])          # head centre (rest)
    eyeL, eyeR = np.array(spec['_eyes'][0]), np.array(spec['_eyes'][1])
    base = np.array(S['tone'])
    col = np.tile(base, (len(p), 1))
    # broad colour variation and pores
    lo = fbm(p, 6, 3, seed=1)[:, None]
    col *= 0.94 + 0.12 * lo
    col *= 0.985 + 0.03 * fbm(p, 300, 2, seed=5)[:, None]
    red = np.array(S.get('flush', (0.78, 0.42, 0.38)))
    rel = p - head
    # warm cheeks, nose, ears, knuckles
    front = 1 / (1 + np.exp((rel[:, 1] + 0.05) / 0.006))   # soft: 1 on the face, 0 towards the ears
    cheek = np.exp(-(((np.abs(rel[:, 0]) - 0.04) / 0.022) ** 2 + ((rel[:, 2] + 0.035) / 0.022) ** 2)) * front
    nose = np.exp(-((rel[:, 0] / 0.012) ** 2 + ((rel[:, 2] + 0.03) / 0.02) ** 2)) * front
    ears = M['ears'][mask]
    flush = np.clip(cheek * S.get('blush', 0.35) + nose * 0.25 + ears * 0.25, 0, 1)[:, None]
    col = col * (1 - flush * 0.35) + red * flush * 0.35
    # lips
    lips = np.clip(M['lips'][mask] * 2.0 - 1.0, 0, 1)[:, None] * S.get('lip_amt', 0.7)
    lipc = np.array(S.get('lips', (0.62, 0.3, 0.3)))
    col = col * (1 - lips) + lipc * (0.9 + 0.1 * lo) * lips
    # inside of the mouth: dark and red, not skin, so an open mouth reads as a mouth
    lw = M['lips'][mask]
    if (lw > 0.5).any():
        lp = p[lw > 0.5]
        mc = lp.mean(0); front = lp[:, 1].min()
        d = p - mc
        # behind the lip line, inside the lip band (philtrum and chin are outside it)
        ny, nz = M['ny'][mask], M['nz'][mask]
        facing_in = np.clip((ny + 0.35) / 0.2, 0, 1) + np.clip((np.abs(nz) - 0.55) / 0.15, 0, 1) * (np.abs(d[:, 2]) < 0.009)
        deep = (np.clip((p[:, 1] - front - 0.003) / 0.003, 0, 1) * np.clip((0.02 - np.abs(d[:, 0])) / 0.006, 0, 1) * (np.abs(d[:, 2]) < 0.012)
                * np.clip(facing_in, 0, 1))
        # the cavity itself: well behind the lips (gums, the back wall), which the face never is this close to the mouth
        behind = p[:, 1] - front
        deep = np.maximum(deep, np.clip((behind - 0.011) / 0.003, 0, 1) * np.clip((0.016 - np.abs(d[:, 0])) / 0.005, 0, 1) * (np.abs(d[:, 2]) < 0.009))
        deep = np.maximum(deep, np.clip((behind - 0.025) / 0.004, 0, 1) * np.clip((0.02 - np.abs(d[:, 0])) / 0.005, 0, 1) * (np.abs(d[:, 2]) < 0.035))
        inner = np.clip(deep, 0, 1)[:, None]       # includes the wet inside of the lips
        col = col * (1 - inner * 0.85) + np.array((0.22, 0.07, 0.07)) * inner * 0.85
    # eyelid shadow / liner
    for e in (eyeL, eyeR):
        d = p - e
        k = spec.get('stylize', {}).get('eyes', 1.0)
        lid = np.exp(-((d[:, 0] / (0.02 * k)) ** 2 + ((d[:, 2] - 0.006 * k) / (0.009 * k)) ** 2)) / (1 + np.exp((d[:, 1] + 0.005) / 0.003))
        col *= (1 - lid * S.get('lid', 0.18))[:, None]
    # waterline: the shelf of the lower lid faces up into the light, so give it the wet, shaded
    # pink of a real lid rim instead of bright skin
    for e in (eyeL, eyeR):
        d = p - e
        sm = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
        near = sm((0.02 - np.abs(d[:, 0])) / 0.005) * sm((0.002 - d[:, 2]) / 0.002) * sm((d[:, 2] + 0.013) / 0.003) * (d[:, 1] < 0.004)
        shelf = (np.clip((M['nz'][mask] - 0.25) / 0.3, 0, 1) * near)[:, None]
        wl = S.get('waterline', 0.75)
        col = col * (1 - shelf * wl) + np.array(S.get('waterline_col', (0.52, 0.3, 0.28))) * shelf * wl
    # lash line: ink along the upper lid rim (the skin's open edge around the eye and the first rings next to it),
    # heavier toward the outer corner
    if S.get('lash'):
        rim = M['rim'][mask]
        R = spec.get('_eye_r', 0.012)
        for e, sg in ((eyeL, 1), (eyeR, -1)):
            d = p - e
            if not (np.linalg.norm(d, axis=1) < 2 * R).any():
                continue
            u = sg * d[:, 0] / R
            near = np.linalg.norm(d, axis=1) < 2 * R
            up = np.clip((d[:, 2] + 0.1 * R + 0.25 * R * np.clip(u, 0, 1)) / (0.12 * R), 0, 1)
            band = np.clip((rim - S.get('lash_t', 0.5)) / 0.15, 0, 1) * up * near * (0.8 + 0.2 * np.clip(u, 0, 1))
            ls = band[:, None] * S['lash']
            col = col * (1 - ls) + np.array((0.08, 0.05, 0.04)) * ls
    # nails
    nails = np.clip(M['nails'][mask], 0, 1)[:, None]
    col = col * (1 - nails * 0.6) + np.array((0.88, 0.7, 0.68)) * nails * 0.6
    hair = np.array(spec['hair']['color'])
    # brows: an arch above each eye, thick at the inner end, drawn as short hair strokes
    br = np.zeros(len(p))
    for e, sg in ((eyeL, 1), (eyeR, -1)):
        d = p - e
        u = sg * d[:, 0]                       # along the brow, + outward
        t = np.clip((u + 0.022) / 0.05, 0, 1)  # 0 inner end .. 1 tail
        zc = S.get('brow_h', 0.021) + 0.007 * np.sin(np.pi * np.clip(t * 1.25, 0, 1)) - S.get('brow_drop', 0.006) * t ** 2
        th = S.get('brow_w', 0.0055) * (1.25 - 0.75 * t)
        inside = np.exp(-((d[:, 2] - zc) / th) ** 4) * (u > -0.024) * (u < 0.031) / (1 + np.exp(d[:, 1] / 0.003))
        ends = np.clip((u + 0.024) / 0.006, 0, 1) * np.clip((0.031 - u) / 0.012, 0, 1)
        br = np.maximum(br, inside * ends)
    strokes = vnoise(p * np.array([0.35, 1.0, 2.5]), 1400, seed=9)
    soft = S.get('brow_soft', 0.0)     # 1: a clean drawn brow instead of hair strokes
    br = np.clip(br * ((0.45 + 0.75 * strokes) * (1 - soft) + soft), 0, 1)[:, None] * S.get('brow', 0.85)
    col = col * (1 - br) + hair * br
    # stubble / scalp shade
    if S.get('stubble'):
        sig = lambda x, w: 1 / (1 + np.exp(-x / w))
        jaw = sig(-0.045 - rel[:, 2], 0.006) * front * sig(0.075 - np.abs(rel[:, 0]), 0.008) * (1 - np.clip(lips[:, 0] * 4, 0, 1))
        upper = sig(0.028 - np.abs(rel[:, 0]), 0.004) * sig(rel[:, 2] + 0.062, 0.003) * sig(-0.047 - rel[:, 2], 0.003) * front * (1 - np.clip(lips[:, 0] * 4, 0, 1))
        st = np.clip(jaw + upper, 0, 1) * S['stubble'] * (0.6 + 0.4 * vnoise(p, 2500, seed=4))
        col = col * (1 - st[:, None] * 0.35) + np.array((0.25, 0.22, 0.2)) * st[:, None] * 0.35
    scalp = np.clip(M['scalp'][mask], 0, 1)[:, None] * (0.6 + 0.4 * vnoise(p, 900, seed=12)[:, None])
    col = col * (1 - scalp * 0.9) + hair * 1.2 * scalp * 0.9
    out = np.zeros((size, size, 3), np.float32)
    out[mask] = col
    out = dilate(out, mask, 6)
    return to_image(spec['name'] + '_skin', out ** (1 / 1.0), f"{outdir}/{spec['name']}_skin.png")


# ---------- fabric (tileable) ----------
def fabric(kind, color, size=512, seed=0):
    """Tileable fabric albedo and normal map. kind: twill, weave, satin, leather, stripe_tie."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size] / size
    c = np.array(color, np.float32)
    def per(f, ph=0):
        return 0.5 + 0.5 * np.sin(2 * np.pi * f + ph)
    if kind == 'twill':
        h = per((xx + yy) * 96) * 0.6 + per(xx * 192) * 0.2 + per(yy * 192) * 0.2
        stripe = 0.0
    elif kind == 'weave':
        h = per(xx * 160) * per(yy * 160 + 0.25)
        stripe = 0.0
    elif kind == 'satin':
        h = per((xx * 0.3 + yy) * 200) * 0.3
        stripe = 0.0
    elif kind == 'leather':
        h = np.zeros_like(xx)
        stripe = 0.0
    else:
        h = per((xx + yy) * 140) * 0.5
        stripe = 0.0
    n = rng.normal(0, 1, (size // 8, size // 8))
    n = np.kron(n, np.ones((8, 8)))
    k = np.fft.fft2(n)
    fy, fx = np.meshgrid(np.fft.fftfreq(size), np.fft.fftfreq(size), indexing='ij')
    k *= np.exp(-(fx ** 2 + fy ** 2) / (2 * 0.02 ** 2))
    slub = np.real(np.fft.ifft2(k))
    slub = (slub - slub.mean()) / (slub.std() + 1e-9)
    if kind == 'leather':
        h = np.clip(0.5 + 0.15 * slub, 0, 1)
    alb = c[None, None] * (0.9 + 0.12 * h[..., None] + 0.04 * slub[..., None])
    if kind == 'stripe_tie':
        band = per((xx + yy) * 4) > 0.93
        alb = np.where(band[..., None], np.array(color[3:6] if len(color) > 3 else (0.8, 0.75, 0.6))[None, None], np.array(color[:3])[None, None] * (0.9 + 0.1 * h[..., None]))
        hh = h
    hh = h + 0.2 * slub
    gy, gx = np.gradient(hh)
    s = 3.0 if kind in ('twill', 'weave', 'stripe_tie') else 1.5
    nrm = np.stack([-gx * s, -gy * s, np.ones_like(gx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    return np.clip(alb[..., :3], 0, 1), nrm * 0.5 + 0.5


# ---------- materials ----------
def material(name, base=None, tex=None, normal=None, rough=0.6, metal=0.0, scale=None, alpha_tex=None, blend=False, double=False, nstrength=0.3):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    if base is not None:
        bsdf.inputs['Base Color'].default_value = (*base, 1)
    mapping = None
    if scale:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        mapping = nt.nodes.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value = (scale, scale, 1)
        nt.links.new(tc.outputs['UV'], mapping.inputs['Vector'])
    if tex is not None:
        t = nt.nodes.new('ShaderNodeTexImage')
        t.image = tex
        if mapping:
            nt.links.new(mapping.outputs['Vector'], t.inputs['Vector'])
        nt.links.new(t.outputs['Color'], bsdf.inputs['Base Color'])
        if alpha_tex == 'self':
            nt.links.new(t.outputs['Alpha'], bsdf.inputs['Alpha'])
    if normal is not None:
        t = nt.nodes.new('ShaderNodeTexImage')
        t.image = normal
        normal.colorspace_settings.name = 'Non-Color'
        if mapping:
            nt.links.new(mapping.outputs['Vector'], t.inputs['Vector'])
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nm.inputs['Strength'].default_value = nstrength
        nt.links.new(t.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    if blend:
        m.surface_render_method = 'BLENDED' if hasattr(m, 'surface_render_method') else None
        m.blend_method = 'BLEND' if hasattr(m, 'blend_method') else None
    m.use_backface_culling = not double
    return m


def set_material(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
