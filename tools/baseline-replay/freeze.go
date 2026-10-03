package main

import (
	"path/filepath"
	"sort"
)

const cohortRelative = "cohorts/ir-composition-curriculum-2026-09-30"
const freezeDigest = "e66f71f3bc02350168bb3958628bf5d1a3e02096ed758cbfbe83f987b71eb9b8"

var archivedSources = map[string]struct{ frozen, current, archive string }{
	"scripts/prepare_ir_composition_curriculum.py": {
		"14abe4cac636ba79479e620f93f06106ce3f413174309f13e4353cf23cc34204",
		"3a495f6833d0f240d697839ecc09d3ac34ea0453ab2e26d972c0899f0e86aeab", "prepare"},
	"scripts/run_ir_composition_curriculum.py": {
		"1999181ad3b1765b0f73346b70dc539433e72a6bdbd05b63778113102d178e35",
		"0a5de34e51d66e8807ce5287ebc7cc65241364440395ba6ac4f3f80f9f083499", "run"},
}

type corpus struct {
	root, cohort, old, corrected, newer, candidate string
	freeze                                         object
	vectors, designs                               map[string]object
	frozenRows                                     []object
}

func loadCorpus(root string) corpus {
	c := corpus{root: root, cohort: filepath.Join(root, cohortRelative)}
	c.old = filepath.Join(c.cohort, "execution/original-gooo-cli-baseline")
	c.corrected = filepath.Join(c.old, "go-validation-corrected-v1")
	c.newer = filepath.Join(c.cohort, "execution/condition-equivalence-60cf7f49")
	c.candidate = filepath.Join(c.cohort, "execution/candidate-oracle-attempt-5/original-candidate-validity")
	raw := readBytes(filepath.Join(c.cohort, "design-freeze.json"))
	require(digest(raw) == freezeDigest, "original design-freeze bytes changed")
	c.freeze = obj(decode(raw))
	require(str(c.freeze["schema"]) == "gooo/ir-composition-design-freeze/v1", "unexpected design freeze schema")
	files := obj(c.freeze["files"])
	require(len(files) == 142, "expected 142 frozen files; found %d", len(files))
	keys := make([]string, 0, len(files))
	for key := range files {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, relative := range keys {
		expected := str(files[relative])
		current := digest(readBytes(local(root, relative)))
		row := object{"path": relative, "expected_sha256": expected, "current_sha256": current, "resolution": "CURRENT_EXACT"}
		if binding, ok := archivedSources[relative]; ok {
			require(expected == binding.frozen && current == binding.current, "version binding changed: %s", relative)
			archive := cohortRelative + "/replay-source-versions-v1/" + binding.archive
			frozenArchive, currentArchive := archive+".frozen.py.txt", archive+".go1271.py.txt"
			require(digest(readBytes(local(root, frozenArchive))) == expected, "frozen archive mismatch: %s", relative)
			require(digest(readBytes(local(root, currentArchive))) == current, "current archive mismatch: %s", relative)
			row["resolution"] = "BOUND_HISTORICAL_ARCHIVE"
			row["frozen_archive"] = frozenArchive
			row["current_archive"] = currentArchive
			row["recovered_source_commit"] = "02e619c153d8313d672636b990e0334d0e87a54b"
		} else {
			require(current == expected, "frozen input hash mismatch: %s", relative)
		}
		c.frozenRows = append(c.frozenRows, row)
	}
	c.vectors = index(decode(readBytes(filepath.Join(c.cohort, "oracle/testdata/vectors.json"))), "id")
	c.designs = index(doc(filepath.Join(c.cohort, "catalog.json"))["designs"], "id")
	require(len(c.vectors) == 32 && sameKeys(c.vectors, c.designs), "expected 32 unique frozen vectors/catalog entries")
	return c
}
