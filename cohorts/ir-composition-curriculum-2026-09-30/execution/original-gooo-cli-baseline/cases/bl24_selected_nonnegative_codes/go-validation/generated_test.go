package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C24(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C24(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_bl24_selected_nonnegative_codes(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-1), expected: int64(0)},,
		{input: int64(0), expected: int64(0)},,
		{input: int64(2), expected: int64(6)},,
		{input: int64(4), expected: int64(6)},,
		{input: int64(5), expected: int64(0)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_bl24_selected_nonnegative_codes(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-100), expected: int64(0)},,
		{input: int64(1), expected: int64(0)},,
		{input: int64(10), expected: int64(0)},
	}
	runFinite(t, "evaluation", cases)
}

