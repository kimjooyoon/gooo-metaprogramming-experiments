package bodycodegen

import "testing"

type finiteCase struct { input, expected int64 }

func runFinite(t *testing.T, suite string, cases []finiteCase) {
	t.Helper()
	for index, item := range cases {
		actual := HarnessSmoke(item.input)
		passed := actual == item.expected
		t.Logf("FINITERESULT|%s|%d|%d|%d|%d|%t", suite, index+1, item.input, item.expected, actual, passed)
		if !passed { t.Errorf("%s case %d: HarnessSmoke(%d) = %d, want %d", suite, index+1, item.input, actual, item.expected) }
	}
}

func TestFrozenTrainingVectors_harness_smoke(t *testing.T) {
	cases := []finiteCase{
		{input: int64(4), expected: int64(4)},
		{input: int64(5), expected: int64(5)},
	}
	runFinite(t, "training", cases)
}

func TestFrozenEvaluationVectors_harness_smoke(t *testing.T) {
	cases := []finiteCase{
		{input: int64(-2), expected: int64(-2)},
		{input: int64(-3), expected: int64(-3)},
	}
	runFinite(t, "evaluation", cases)
}

