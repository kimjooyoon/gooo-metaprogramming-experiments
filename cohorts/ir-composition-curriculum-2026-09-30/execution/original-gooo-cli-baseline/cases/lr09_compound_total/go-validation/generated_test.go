package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C09(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C09(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_lr09_compound_total(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-5), expected: int64(0)},,
		{input: int64(0), expected: int64(10)},,
		{input: int64(1), expected: int64(12)},,
		{input: int64(4), expected: int64(18)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_lr09_compound_total(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(-10)},,
		{input: int64(8), expected: int64(26)},,
		{input: int64(10), expected: int64(30)},
	}
	runFinite(t, "evaluation", cases)
}

