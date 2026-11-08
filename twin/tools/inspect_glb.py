"""Print what a viewer needs to know about .glb files: animation clips, external
texture URIs, mesh bounding box (size + long axis), and for skinned humans the
facing direction (toe minus foot, in bind pose, world space).
Usage (from simulation/): uv run python -m tools.inspect_glb ../viewer/public/models/cars/sedan.glb [...]
"""
import json
import struct
import sys

import numpy as np


def read_json(path):
    with open(path, "rb") as f:
        data = f.read()
    length = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + length])


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def local_matrix(node):
    m = np.eye(4)
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    r = quat_to_mat(node.get("rotation", [0, 0, 0, 1]))
    s = np.diag(node.get("scale", [1, 1, 1]))
    m[:3, :3] = r @ s
    m[:3, 3] = node.get("translation", [0, 0, 0])
    return m


def world_matrices(gltf):
    nodes = gltf["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    cache = {}

    def world(i):
        if i not in cache:
            m = local_matrix(nodes[i])
            cache[i] = world(parent[i]) @ m if i in parent else m
        return cache[i]

    return [world(i) for i in range(len(nodes))]


def main():
    for path in sys.argv[1:]:
        g = read_json(path)
        print(f"== {path.split('/')[-1]}")
        print("  animations:", [a.get("name") for a in g.get("animations", [])])
        print("  external uris:", [i["uri"] for i in g.get("images", []) if "uri" in i]
              + [b["uri"] for b in g.get("buffers", []) if "uri" in b])
        worlds = world_matrices(g)
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for i, n in enumerate(g["nodes"]):
            if "mesh" not in n:
                continue
            for prim in g["meshes"][n["mesh"]]["primitives"]:
                acc = g["accessors"][prim["attributes"]["POSITION"]]
                for corner in np.array(np.meshgrid(*zip(acc["min"], acc["max"]))).T.reshape(-1, 3):
                    p = worlds[i] @ np.append(corner, 1)
                    lo, hi = np.minimum(lo, p[:3]), np.maximum(hi, p[:3])
        size = hi - lo
        print("  bbox min", lo.round(2), "max", hi.round(2), "size xyz", size.round(2))
        names = {n.get("name", ""): i for i, n in enumerate(g["nodes"])}
        foot = next((k for k in names if "leftfoot" in k.lower().replace("_", "").replace(":", "")), None)
        toe = next((k for k in names if "lefttoe" in k.lower().replace("_", "").replace(":", "")), None)
        if foot and toe:
            d = worlds[names[toe]][:3, 3] - worlds[names[foot]][:3, 3]
            print(f"  facing (toe-foot, {foot}->{toe}):", (d / np.linalg.norm(d)).round(2))


if __name__ == "__main__":
    main()
