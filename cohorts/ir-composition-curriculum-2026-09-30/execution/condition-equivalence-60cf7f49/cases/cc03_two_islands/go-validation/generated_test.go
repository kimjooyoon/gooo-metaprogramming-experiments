package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C03(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C03(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_cc03_two_islands(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-5), expected: int64(0)},
		{input: int64(-4), expected: int64(7)},
		{input: int64(0), expected: int64(0)},
		{input: int64(4), expected: int64(7)},
		{input: int64(5), expected: int64(0)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_cc03_two_islands(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-100), expected: int64(0)},
		{input: int64(2), expected: int64(0)},
	}
	runFinite(t, "evaluation", cases)
}

