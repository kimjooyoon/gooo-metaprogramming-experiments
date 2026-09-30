package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C01(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C01(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_cc01_inclusive_band(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-1), expected: int64(-1)},
		{input: int64(2), expected: int64(-1)},
		{input: int64(3), expected: int64(2)},
		{input: int64(8), expected: int64(2)},
		{input: int64(9), expected: int64(-1)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_cc01_inclusive_band(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(-1)},
		{input: int64(4), expected: int64(2)},
		{input: int64(12), expected: int64(-1)},
	}
	runFinite(t, "evaluation", cases)
}

