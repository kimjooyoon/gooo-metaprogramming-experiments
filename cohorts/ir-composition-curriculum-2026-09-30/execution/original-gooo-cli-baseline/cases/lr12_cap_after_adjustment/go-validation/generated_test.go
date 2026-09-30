package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C12(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C12(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_lr12_cap_after_adjustment(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-5), expected: int64(-3)},,
		{input: int64(0), expected: int64(2)},,
		{input: int64(7), expected: int64(9)},,
		{input: int64(8), expected: int64(9)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_lr12_cap_after_adjustment(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-20), expected: int64(-18)},,
		{input: int64(10), expected: int64(9)},,
		{input: int64(100), expected: int64(9)},
	}
	runFinite(t, "evaluation", cases)
}

