package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C26(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C26(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_tx26_state_label(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-1), expected: int64(0)},
		{input: int64(0), expected: int64(0)},
		{input: int64(1), expected: int64(1)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_tx26_state_label(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-20), expected: int64(0)},
		{input: int64(7), expected: int64(1)},
	}
	runFinite(t, "evaluation", cases)
}

