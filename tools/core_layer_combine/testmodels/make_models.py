"""Erzeugt die Testmodelle aus dem Testplan des Lastenhefts als ASCII-STL.

    python make_models.py [zielordner]

Modelle (Maße in mm):
  wuerfel20.stl     Würfel 20 mm                                   F-12/F-14/F-30
  pyramide.stl      Pyramide 40 x 40, Höhe 30                      Kaskade an Schrägen, F-13
  halter.stl        Halter mit Absatz, 2 Bohrungen, Top-Fläche     F-15/F-17/F-18
                    mitten im Teil
  zugstab_1A.stl    Zugstab ISO 527-2 Typ 1A, liegend, 4 mm dick   Festigkeit
  duennwand.stl     Rohr 30 x 30, Wand 1,6 mm, Höhe 20             V-05, F-18
  testeck.stl       Quader 100 x 50 x 10 (Modell der Referenz       Vergleich mit
                    Testeck_CLC3_optimiert.gcode)                  der Referenz

Bohrungen und Hohlräume entstehen aus sich berührenden Quadern; der Slicer
vereinigt die Teilkörper je Schicht.
"""
import math
import os
import sys


def ear_clip(poly):
    """Dreieckszerlegung eines einfachen Polygons (gegen den Uhrzeigersinn)."""
    idx = list(range(len(poly)))
    tris = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    guard = 0
    while len(idx) > 3 and guard < 100000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            raise ValueError("Polygon nicht zerlegbar")
    tris.append(tuple(idx))
    return tris


def prism(poly, z0, z1):
    """Prisma aus einem einfachen Polygon (CCW), Rückgabe: Liste von Dreiecken."""
    out = []
    for i0, i1, i2 in ear_clip(poly):
        a, b, c = poly[i0], poly[i1], poly[i2]
        out.append(((a[0], a[1], z1), (b[0], b[1], z1), (c[0], c[1], z1)))
        out.append(((a[0], a[1], z0), (c[0], c[1], z0), (b[0], b[1], z0)))
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        out.append(((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)))
        out.append(((a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)))
    return out


def box(x0, y0, z0, x1, y1, z1):
    return prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1)


def pyramid(w, h):
    a = (-w / 2, -w / 2, 0)
    b = (w / 2, -w / 2, 0)
    c = (w / 2, w / 2, 0)
    d = (-w / 2, w / 2, 0)
    t = (0, 0, h)
    return [(a, c, b), (a, d, c), (a, b, t), (b, c, t), (c, d, t), (d, a, t)]


def dogbone():
    """ISO 527-2 Typ 1A: l3 = 170, b2 = 20, b1 = 10, l1 = 80, r = 24, h = 4."""
    l3, b2, b1, l1, r = 170.0, 20.0, 10.0, 80.0, 24.0
    dy = (b2 - b1) / 2                       # 5 mm Absatz je Seite
    dx = math.sqrt(r * r - (r - dy) ** 2)    # Länge des Übergangsradius
    x_par = l1 / 2
    # obere Kontur der rechten Hälfte, aufsteigend in x
    right = [(0.0, b1 / 2), (x_par, b1 / 2)]
    steps = 16
    for i in range(1, steps + 1):
        t = i / steps * dx
        # Kreis mit Mittelpunkt (x_par, b1/2 + r), tangential an die Parallele
        right.append((x_par + t, b1 / 2 + r - math.sqrt(r * r - t * t)))
    right.append((l3 / 2, b2 / 2))
    upper = [(-x, y) for x, y in reversed(right)] + right[1:]   # aufsteigend in x
    lower = [(x, -y) for x, y in upper]
    poly = lower + list(reversed(upper))                       # gegen den Uhrzeigersinn
    return prism(poly, 0.0, 4.0)


def halter():
    """Grundplatte 60 x 30 x 6 mit zwei 8-mm-Bohrungen (quadratisch), darauf ein
    Turm 24 x 30 x 14 am linken Ende. Die Oberseite der Platte rechts ist eine
    Top-Fläche mitten im Teil (Z = 6)."""
    t = []
    # Grundplatte aus Streifen, die zwei Bohrungen 8 x 8 bei x = 30..38 und 46..54 freilassen
    t += box(0, 0, 0, 30, 30, 6)
    t += box(30, 0, 0, 60, 11, 6)
    t += box(30, 19, 0, 60, 30, 6)
    t += box(38, 11, 0, 46, 19, 6)
    t += box(54, 11, 0, 60, 19, 6)
    # Turm
    t += box(0, 0, 6, 24, 30, 20)
    return t


def duennwand():
    t = []
    w, s, h = 30.0, 1.6, 20.0
    t += box(0, 0, 0, w, s, h)
    t += box(0, w - s, 0, w, w, h)
    t += box(0, s, 0, s, w - s, h)
    t += box(w - s, s, 0, w, w - s, h)
    t += box(0, 0, 0, w, w, 1.0)  # Boden
    return t


def write_stl(path, name, tris):
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(f"solid {name}\n")
        for a, b, c in tris:
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            f.write(f"  facet normal {nx / ln:.6f} {ny / ln:.6f} {nz / ln:.6f}\n    outer loop\n")
            for p in (a, b, c):
                f.write(f"      vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
            f.write("    endloop\n  endfacet\n")
        f.write(f"endsolid {name}\n")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    models = {
        "wuerfel20": box(0, 0, 0, 20, 20, 20),
        "pyramide": pyramid(40.0, 30.0),
        "halter": halter(),
        "zugstab_1A": dogbone(),
        "duennwand": duennwand(),
        "testeck": box(0, 0, 0, 100, 50, 10),
    }
    for name, tris in models.items():
        write_stl(os.path.join(out, name + ".stl"), name, tris)
        print(f"{name}.stl: {len(tris)} Dreiecke")


if __name__ == "__main__":
    main()
