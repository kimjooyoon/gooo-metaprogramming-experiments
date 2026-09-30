package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct { DesignID string; ProbeID string; Index int; Input int64 }
type extraCandidateResult struct { DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }

func TestExtraDomainProbeCandidate(t *testing.T) {
    cases := []extraCandidateCase{{DesignID:"lr11_nonnegative_doubled_score", ProbeID:"lr11_nonnegative_doubled_score/x1", Index:0, Input:-3},
{DesignID:"lr11_nonnegative_doubled_score", ProbeID:"lr11_nonnegative_doubled_score/x2", Index:1, Input:1},
{DesignID:"lr11_nonnegative_doubled_score", ProbeID:"lr11_nonnegative_doubled_score/x3", Index:2, Input:4611686018427387903},
{DesignID:"lr11_nonnegative_doubled_score", ProbeID:"lr11_nonnegative_doubled_score/x4", Index:3, Input:9223372036854775807}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {
        results = append(results, extraCandidateResult{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:C11(item.Input)})
    }
    encoded, err := json.Marshal(results)
    if err != nil { t.Fatal(err) }
    t.Logf("EXTRA_DOMAIN_CANDIDATE_RESULT:%s", encoded)
}
