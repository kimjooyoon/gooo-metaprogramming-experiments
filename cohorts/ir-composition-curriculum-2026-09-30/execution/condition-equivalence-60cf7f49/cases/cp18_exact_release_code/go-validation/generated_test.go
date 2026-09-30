package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C18(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C18(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_cp18_exact_release_code(t *testing.T) {
	cases := []finiteCase{
		{input: int64(6), expected: int64(0)},
		{input: int64(7), expected: int64(1)},
		{input: int64(8), expected: int64(0)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_cp18_exact_release_code(t *testing.T) {
	cases := []finiteCase{
		{input: int64(0), expected: int64(0)},
		{input: int64(9), expected: int64(0)},
		{input: int64(100), expected: int64(0)},
	}
	runFinite(t, "evaluation", cases)
}

