package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C30(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C30(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_ob30_saturating_decrement(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-9223372036854775806), expected: int64(-9223372036854775807)},
		{input: int64(-9223372036854775807), expected: int64(-9223372036854775808)},
		{input: int64(0), expected: int64(-1)},
		{input: int64(1), expected: int64(0)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_ob30_saturating_decrement(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-9223372036854775808), expected: int64(-9223372036854775808)},
		{input: int64(-9223372036854775805), expected: int64(-9223372036854775806)},
		{input: int64(10), expected: int64(9)},
	}
	runFinite(t, "evaluation", cases)
}

