package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct { DesignID string; ProbeID string; Index int; Input int64 }
type extraCandidateResult struct { DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }

func TestExtraDomainProbeCandidate(t *testing.T) {
    cases := []extraCandidateCase{{DesignID:"pr13_subtract_tripled_sum", ProbeID:"pr13_subtract_tripled_sum/x1", Index:0, Input:-3},
{DesignID:"pr13_subtract_tripled_sum", ProbeID:"pr13_subtract_tripled_sum/x2", Index:1, Input:-1},
{DesignID:"pr13_subtract_tripled_sum", ProbeID:"pr13_subtract_tripled_sum/x3", Index:2, Input:4},
{DesignID:"pr13_subtract_tripled_sum", ProbeID:"pr13_subtract_tripled_sum/x4", Index:3, Input:9223372036854775807}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {
        results = append(results, extraCandidateResult{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:C13(item.Input)})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    t.Logf("EXTRA_DOMAIN_CANDIDATE_RESULT:%s", encoded)
}
