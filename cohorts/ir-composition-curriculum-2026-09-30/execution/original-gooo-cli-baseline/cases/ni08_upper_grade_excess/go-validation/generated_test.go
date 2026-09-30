package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C08(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C08(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_ni08_upper_grade_excess(t *testing.T) {
	cases := []finiteCase{
		{input: int64(59), expected: int64(-1)},,
		{input: int64(60), expected: int64(0)},,
		{input: int64(79), expected: int64(0)},,
		{input: int64(80), expected: int64(0)},,
		{input: int64(81), expected: int64(1)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_ni08_upper_grade_excess(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-1), expected: int64(-1)},,
		{input: int64(70), expected: int64(0)},,
		{input: int64(100), expected: int64(20)},
	}
	runFinite(t, "evaluation", cases)
}

