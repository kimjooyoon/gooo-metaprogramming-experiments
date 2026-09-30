package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C13(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C13(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_pr13_subtract_tripled_sum(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-2), expected: int64(100)},,
		{input: int64(0), expected: int64(94)},,
		{input: int64(3), expected: int64(85)},,
		{input: int64(5), expected: int64(79)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_pr13_subtract_tripled_sum(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(124)},,
		{input: int64(7), expected: int64(73)},,
		{input: int64(20), expected: int64(34)},
	}
	runFinite(t, "evaluation", cases)
}

