package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct { DesignID string; ProbeID string; Index int; Input int64 }
type extraCandidateResult struct { DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }

func TestExtraDomainProbeCandidate(t *testing.T) {
    cases := []extraCandidateCase{{DesignID:"cp17_nonpositive_inclusive", ProbeID:"cp17_nonpositive_inclusive/x1", Index:0, Input:-2},
{DesignID:"cp17_nonpositive_inclusive", ProbeID:"cp17_nonpositive_inclusive/x2", Index:1, Input:2},
{DesignID:"cp17_nonpositive_inclusive", ProbeID:"cp17_nonpositive_inclusive/x3", Index:2, Input:-1000},
{DesignID:"cp17_nonpositive_inclusive", ProbeID:"cp17_nonpositive_inclusive/x4", Index:3, Input:1000}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {
        results = append(results, extraCandidateResult{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:C17(item.Input)})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    t.Logf("EXTRA_DOMAIN_CANDIDATE_RESULT:%s", encoded)
}
