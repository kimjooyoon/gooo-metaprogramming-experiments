package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C16(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C16(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_pr16_composed_neighbor_product(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-3), expected: int64(5)},,
		{input: int64(0), expected: int64(2)},,
		{input: int64(2), expected: int64(10)},,
		{input: int64(5), expected: int64(37)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_pr16_composed_neighbor_product(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-10), expected: int64(82)},,
		{input: int64(4), expected: int64(26)},,
		{input: int64(12), expected: int64(170)},
	}
	runFinite(t, "evaluation", cases)
}

