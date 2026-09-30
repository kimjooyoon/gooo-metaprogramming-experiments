package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C20(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C20(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_cp20_strict_symmetric_window(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-6), expected: int64(-4)},
		{input: int64(-5), expected: int64(-4)},
		{input: int64(-4), expected: int64(4)},
		{input: int64(4), expected: int64(4)},
		{input: int64(5), expected: int64(-4)},
		{input: int64(6), expected: int64(-4)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_cp20_strict_symmetric_window(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-100), expected: int64(-4)},
		{input: int64(0), expected: int64(4)},
		{input: int64(100), expected: int64(-4)},
	}
	runFinite(t, "evaluation", cases)
}

