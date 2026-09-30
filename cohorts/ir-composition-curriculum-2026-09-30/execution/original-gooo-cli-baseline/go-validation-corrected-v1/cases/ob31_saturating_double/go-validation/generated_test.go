package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C31(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C31(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_ob31_saturating_double(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-2), expected: int64(-4)},
		{input: int64(-1), expected: int64(-2)},
		{input: int64(0), expected: int64(0)},
		{input: int64(1), expected: int64(2)},
		{input: int64(2), expected: int64(4)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_ob31_saturating_double(t *testing.T) {
	cases := []finiteCase{
		{input: int64(9223372036854775807), expected: int64(9223372036854775807)},
		{input: int64(4611686018427387903), expected: int64(9223372036854775806)},
		{input: int64(4611686018427387904), expected: int64(9223372036854775807)},
		{input: int64(-9223372036854775808), expected: int64(-9223372036854775808)},
		{input: int64(-4611686018427387904), expected: int64(-9223372036854775808)},
		{input: int64(-4611686018427387905), expected: int64(-9223372036854775808)},
	}
	runFinite(t, "evaluation", cases)
}

