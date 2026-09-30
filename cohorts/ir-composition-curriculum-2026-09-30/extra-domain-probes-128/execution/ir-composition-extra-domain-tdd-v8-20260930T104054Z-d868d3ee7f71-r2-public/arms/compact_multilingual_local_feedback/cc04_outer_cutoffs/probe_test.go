package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct { DesignID string; ProbeID string; Index int; Input int64 }
type extraCandidateResult struct { DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }

func TestExtraDomainProbeCandidate(t *testing.T) {
    cases := []extraCandidateCase{{DesignID:"cc04_outer_cutoffs", ProbeID:"cc04_outer_cutoffs/x1", Index:0, Input:-8},
{DesignID:"cc04_outer_cutoffs", ProbeID:"cc04_outer_cutoffs/x2", Index:1, Input:-4},
{DesignID:"cc04_outer_cutoffs", ProbeID:"cc04_outer_cutoffs/x3", Index:2, Input:6},
{DesignID:"cc04_outer_cutoffs", ProbeID:"cc04_outer_cutoffs/x4", Index:3, Input:10}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {
        results = append(results, extraCandidateResult{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:C04(item.Input)})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    t.Logf("EXTRA_DOMAIN_CANDIDATE_RESULT:%s", encoded)
}
