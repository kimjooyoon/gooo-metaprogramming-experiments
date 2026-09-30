package bodycodegen

import (
    "encoding/json"
    "os"
    "testing"
)

func TestFrozenTrainingAndEvaluationCases(t *testing.T) {
    cases := []struct { split string; input, expected int64 }{
		{split: "training", input: -2, expected: -4},
		{split: "training", input: -1, expected: -2},
		{split: "training", input: 0, expected: 0},
		{split: "training", input: 1, expected: 2},
		{split: "training", input: 2, expected: 4},
		{split: "evaluation", input: 9223372036854775807, expected: 9223372036854775807},
		{split: "evaluation", input: 4611686018427387903, expected: 9223372036854775806},
		{split: "evaluation", input: 4611686018427387904, expected: 9223372036854775807},
		{split: "evaluation", input: -9223372036854775808, expected: -9223372036854775808},
		{split: "evaluation", input: -4611686018427387904, expected: -9223372036854775808},
		{split: "evaluation", input: -4611686018427387905, expected: -9223372036854775808}
    }
    results := make([]struct {
        Split string `json:"split"`
        Input int64 `json:"input"`
        Expected int64 `json:"expected"`
        Actual int64 `json:"actual"`
        Passed bool `json:"passed"`
    }, 0, len(cases))
    for _, item := range cases {
        actual := C31(item.input)
        results = append(results, struct {
            Split string `json:"split"`
            Input int64 `json:"input"`
            Expected int64 `json:"expected"`
            Actual int64 `json:"actual"`
            Passed bool `json:"passed"`
        }{Split:item.split, Input:item.input, Expected:item.expected, Actual:actual, Passed:actual==item.expected})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    if err := os.WriteFile("execution-results.json", encoded, 0o644); err != nil { t.Fatal(err) }
    for _, item := range results {
        if !item.Passed { t.Errorf("%s(%d) = %d, want %d", item.Split, item.Input, item.Actual, item.Expected) }
    }
}
