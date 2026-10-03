# Historical preparation source versions

The original study freezes two script digests:

| Original path | Original SHA256 | Go1.27.1 revision SHA256 |
| --- | --- | --- |
| `scripts/prepare_ir_composition_curriculum.py` | `14abe4cac636ba79479e620f93f06106ce3f413174309f13e4353cf23cc34204` | `3a495f6833d0f240d697839ecc09d3ac34ea0453ab2e26d972c0899f0e86aeab` |
| `scripts/run_ir_composition_curriculum.py` | `1999181ad3b1765b0f73346b70dc539433e72a6bdbd05b63778113102d178e35` | `0a5de34e51d66e8807ce5287ebc7cc65241364440395ba6ac4f3f80f9f083499` |

The `.frozen.py.txt` bytes come from commit
`02e619c153d8313d672636b990e0334d0e87a54b`. The `.go1271.py.txt` bytes preserve the
current files after toolchain update `bd209e8695c166c4cff33d079f6a2227c8119f97`.
The active files retain Go1.27.1. All four archives are historical source data.

The original freeze digest stays
`e66f71f3bc02350168bb3958628bf5d1a3e02096ed758cbfbe83f987b71eb9b8`.
The [Go replay tool](../../../tools/baseline-replay) checks every archive and
current file against its explicit binding, then replays the saved Go modules.
No archived preparation script is executed and no old result is regenerated.

Revision-2 also retains `revision2-prepare.frozen.py.txt` and
`revision2-prepare.go1271.py.txt`. Their exact digests are bound in the Go
validator's `revision2.go`. The frozen preparer comes from the same historical
commit; the active preparer keeps Go1.27.1. These files are read as source data.
