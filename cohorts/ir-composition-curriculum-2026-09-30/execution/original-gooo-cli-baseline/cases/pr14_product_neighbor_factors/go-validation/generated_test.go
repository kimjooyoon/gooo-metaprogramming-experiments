package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C14(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C14(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_pr14_product_neighbor_factors(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-3), expected: int64(25)},,
		{input: int64(0), expected: int64(-2)},,
		{input: int64(2), expected: int64(0)},,
		{input: int64(5), expected: int64(33)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_pr14_product_neighbor_factors(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(228)},,
		{input: int64(4), expected: int64(18)},,
		{input: int64(10), expected: int64(168)},
	}
	runFinite(t, "evaluation", cases)
}

