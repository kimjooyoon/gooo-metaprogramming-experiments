package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct { DesignID string; ProbeID string; Index int; Input int64 }
type extraCandidateResult struct { DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }

func TestExtraDomainProbeCandidate(t *testing.T) {
    cases := []extraCandidateCase{{DesignID:"cp19_range_without_origin", ProbeID:"cp19_range_without_origin/x1", Index:0, Input:-2},
{DesignID:"cp19_range_without_origin", ProbeID:"cp19_range_without_origin/x2", Index:1, Input:-1},
{DesignID:"cp19_range_without_origin", ProbeID:"cp19_range_without_origin/x3", Index:2, Input:1},
{DesignID:"cp19_range_without_origin", ProbeID:"cp19_range_without_origin/x4", Index:3, Input:5}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {
        results = append(results, extraCandidateResult{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:C19(item.Input)})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    t.Logf("EXTRA_DOMAIN_CANDIDATE_RESULT:%s", encoded)
}
