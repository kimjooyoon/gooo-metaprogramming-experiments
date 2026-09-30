package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C32(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C32(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_ob32_clamped_absolute(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-3), expected: int64(3)},
		{input: int64(0), expected: int64(0)},
		{input: int64(5), expected: int64(5)},
		{input: int64(7), expected: int64(7)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_ob32_clamped_absolute(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-9223372036854775808), expected: int64(9223372036854775807)},
		{input: int64(-9223372036854775807), expected: int64(9223372036854775807)},
		{input: int64(9223372036854775807), expected: int64(9223372036854775807)},
	}
	runFinite(t, "evaluation", cases)
}

