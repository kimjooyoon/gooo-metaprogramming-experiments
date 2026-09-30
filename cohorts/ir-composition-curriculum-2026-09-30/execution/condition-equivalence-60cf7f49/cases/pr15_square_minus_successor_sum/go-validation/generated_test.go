package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C15(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C15(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_pr15_square_minus_successor_sum(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-2), expected: int64(2)},
		{input: int64(0), expected: int64(-4)},
		{input: int64(3), expected: int64(2)},
		{input: int64(6), expected: int64(26)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_pr15_square_minus_successor_sum(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(106)},
		{input: int64(5), expected: int64(16)},
		{input: int64(20), expected: int64(376)},
	}
	runFinite(t, "evaluation", cases)
}

