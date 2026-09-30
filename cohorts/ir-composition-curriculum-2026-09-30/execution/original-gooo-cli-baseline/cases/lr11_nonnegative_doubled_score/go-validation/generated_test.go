package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C11(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C11(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_lr11_nonnegative_doubled_score(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-2), expected: int64(0)},,
		{input: int64(-1), expected: int64(0)},,
		{input: int64(0), expected: int64(1)},,
		{input: int64(2), expected: int64(5)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_lr11_nonnegative_doubled_score(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(0)},,
		{input: int64(3), expected: int64(7)},,
		{input: int64(10), expected: int64(21)},
	}
	runFinite(t, "evaluation", cases)
}

