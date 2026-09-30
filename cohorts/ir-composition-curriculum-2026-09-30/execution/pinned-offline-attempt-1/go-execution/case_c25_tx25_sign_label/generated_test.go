package bodycodegen

import (
    "encoding/json"
    "os"
    "testing"
)

func TestFrozenTrainingAndEvaluationCases(t *testing.T) {
    cases := []struct { split string; input, expected int64 }{
		{split: "training", input: -1, expected: -1},
		{split: "training", input: 0, expected: 1},
		{split: "training", input: 1, expected: 1},
		{split: "evaluation", input: -20, expected: -1},
		{split: "evaluation", input: 20, expected: 1}
    }
    results := make([]struct {
        Split string `json:"split"`
        Input int64 `json:"input"`
        Expected int64 `json:"expected"`
        Actual int64 `json:"actual"`
        Passed bool `json:"passed"`
    }, 0, len(cases))
    for _, item := range cases {
        actual := C25(item.input)
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
