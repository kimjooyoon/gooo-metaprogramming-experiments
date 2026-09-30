package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := C06(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: C06(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_ni06_surcharge_discount(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-1), expected: int64(0)},
		{input: int64(0), expected: int64(10)},
		{input: int64(1), expected: int64(11)},
		{input: int64(100), expected: int64(110)},
		{input: int64(101), expected: int64(91)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_ni06_surcharge_discount(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-5), expected: int64(0)},
		{input: int64(50), expected: int64(60)},
		{input: int64(111), expected: int64(101)},
	}
	runFinite(t, "evaluation", cases)
}

