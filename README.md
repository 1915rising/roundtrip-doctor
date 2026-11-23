# Roundtrip Doctor

A gate for Blender sidecar trips — proof that taking a `.blend`
into a second Blender version and back changed **only the seam
flags you meant to change**, and nothing else.

Some tools only exist for Blender 5.x (extensions with a 5.0+
version floor — Sculpt UVs, which paints UV seams directly on the
mesh, is the one that motivated this). Production pipelines sit on
the 4.2 LTS. The working pattern is a sidecar trip: open the file
in the 5.x seat, do the one job only that seat can do, and bring
the work back. Seam flags are plain mesh data, so in principle they
travel. In practice, "it travels fine" was a claim verified by hand
exactly once, inside the 5.x session itself.

Roundtrip Doctor turns that trip into a gated operation with
receipts — and its first real run found something nobody had
checked:

## The format wall (read this first)

**Blender 5.x saves a new `.blend` file format that Blender 4.2
cannot open at all.** Not "opens with warnings" — 4.2.3 rejects a
5.x-saved file with *"Failed to read blend file … not a blend
file"*. So the naive round trip (save in 5.x, reopen in 4.2) does
not exist. What crosses back is not the file; it is the seam **set**,
extracted as data and re-applied to the 4.2 file. The protocol
below is shaped by that fact, and the verifier gates both legs of
it.

## What it checks

For every mesh object in the BEFORE and AFTER files:

| Channel | Method |
|---|---|
| Vertex coordinates | SHA256 of the float32 coordinate array |
| Edge topology | SHA256 of the edge vertex-pair array |
| Face topology | SHA256 of loop structure + loop vertex indices |
| UV coordinates | SHA256 per UV layer, matched by layer name |
| Seam flags | Reported as an explicit added/removed edge-index delta — the one change allowed |

Verdict is **PASS** only if every non-seam channel is byte-identical
and the only difference anywhere is seam flags. A moved vertex, a
retriangulated face, a touched UV, a vanished object — each fails
the gate and is named in the report. Exit codes make it scriptable:
`0` PASS, `1` FAIL, `2` usage/file error (which is also what you
get, correctly, if you point it at a 5.x file from 4.2).

## The round-trip protocol

1. **Snapshot the gate.** Keep the pre-trip file as BEFORE. Never
   edit it in the sidecar seat — work on a copy.
2. **Trip.** Open the copy in the 5.x seat, do the seam work, save
   as AFTER (a 5.x-format file; it will never be opened by 4.2).
3. **Leg 1 — verify the edit, in the 5.x seat.** The newer seat
   reads both formats, and this tool is plain Blender Python, so
   run the same verifier there: BEFORE vs AFTER must PASS, with a
   seam delta of exactly the edges you painted.
4. **Extract the seam set.** From AFTER, dump the target object's
   seam edges as sorted vertex-index pairs (edge identity that
   survives any faithful load of the same mesh). JSON is fine.
5. **Leg 2 — re-apply and verify, in the 4.2 seat.** Apply the seam
   set to the BEFORE file in 4.2, save as RETURNED, and run the
   verifier on BEFORE vs RETURNED: PASS, with a seam delta of
   exactly the applied edges, is the receipt that the trip is done
   and the file in your pipeline is the file you think it is.

`tests/gown_roundtrip.py` runs this entire protocol end to end —
including a demonstration of the format wall and a negative test —
against a real production mesh (see *Tested on*).

## Usage

```bash
# The gate itself (Blender 4.2.3, background mode is fine):
blender -b --python roundtrip_doctor.py -- before.blend after.blend
blender -b --python roundtrip_doctor.py -- before.blend after.blend \
    --object GenGown --json report.json --report report.txt
```

Or from a Blender Python session (either seat — the code is
version-agnostic; only the file format is one-way):

```python
import roundtrip_doctor as rd

ok, report = rd.verify("before.blend", "after.blend")
print(rd.format_report(report))
```

## Tests

```bash
# Synthetic suite (Blender 4.2.3): identical copy, seams-only,
# moved vertex, moved UV, topology change, removed object,
# CLI exit codes:
blender -b --factory-startup --python tests/run_tests.py

# The full two-leg protocol on the real gown mesh, driving a
# Blender 5.3 sidecar seat (Ensō under Wine) and Blender 4.2.3.
# Paths default to the development machine's layout; see the
# driver's docstring for the RTD_* overrides:
python3 tests/gown_roundtrip.py
```

Example reports from the gown run are in
[`examples/`](examples/): the 4.2-seat receipt for the returned
file, the 5.x-seat receipt for the edit leg, and the negative
report (one vertex moved 1 mm — caught, channel named).

## Known blind spots (v1, stated on purpose)

- **Mesh data only, and only the channels listed.** Shape-key
  data, vertex groups, materials, object transforms, modifiers and
  non-mesh objects are **not** gated. If your sidecar workflow can
  touch those, this tool does not watch them yet.
- **The seam delta speaks edge indices**, which are only a shared
  language because identical edge topology is itself a gated
  channel. If topology changed, the gate fails first and the seam
  delta is reported as not comparable.
- **Hashes are computed by the seat that reads the files.** A leg
  is verified by one Blender reading both of its files (the 5.x
  seat for leg 1, 4.2 for leg 2). That is the strongest comparison
  available across the format wall, and the protocol is honest
  about which seat produced which receipt.
- **Brush feel is not data.** This tool proves the seam *data*
  survived. Whether the painted seams are *good* seams is a
  judgement call no hash can make.

## Tested on

A female avatar's Christmas gown blend (17 mesh objects; target `GenGown`,
17,716 verts / 52,316 edges / 34,561 faces): a 43-edge seam chain
painted in a Blender 5.3 sidecar seat via Sculpt UVs' write path.
Leg 1 (5.x seat): PASS — delta exactly the 43 painted edges, all 16
other objects byte-identical; a full draw+erase cycle PASSed with
zero delta. Leg 2 (4.2.3): the seam set re-applied to the 4.2 file
PASSed with exactly the 43 applied edges. Negative: one vertex
moved 1 mm — FAIL, vertices channel named. Full driver output:
13/13 checks PASS (`tests/gown_roundtrip.py`).

Other meshes and other sidecar tools are **untested**. Issues and
reports from other pipelines are welcome.

## License

MIT — see [LICENSE](LICENSE). The sidecar tools this protocol is
used with (Sculpt UVs, Ensō Engine) are GPL and remain in their own
seat, invoked, never bundled.
