package main

import (
    "encoding/json"
    "fmt"
    "os"
    oracle "example.invalid/gooo/ir-composition-oracle"
)

type row struct { Input int64 `json:"input"`; Expected int64 `json:"expected"` }
type vector struct { ID string `json:"id"`; Training []row `json:"training"`; Evaluation []row `json:"evaluation"` }
type designResult struct { ID string `json:"id"`; Training []rowResult `json:"training"`; Evaluation []rowResult `json:"evaluation"`; CandidateTrainingOutputs map[string][]int64 `json:"candidate_outputs_by_training_input"`; CandidateEvaluationOutputs map[string][]int64 `json:"candidate_outputs_by_evaluation_input"`; GoldCandidate string `json:"gold_candidate"`; DiscriminatingInputs map[string][]int64 `json:"gold_discriminating_inputs"` }
type rowResult struct { Input int64 `json:"input"`; Expected int64 `json:"expected"`; Actual int64 `json:"actual"`; Passed bool `json:"passed"` }
type candidateFunc func(int64) int64
var candidates = map[string]map[string]candidateFunc{
"cc01_inclusive_band": {"option_a": oracle.Candidate01a, "option_b": oracle.Candidate01b, "option_c": oracle.Candidate01c},
"cc02_nonzero_disjunction": {"option_a": oracle.Candidate02a, "option_b": oracle.Candidate02b, "option_c": oracle.Candidate02c},
"cc03_two_islands": {"option_a": oracle.Candidate03a, "option_b": oracle.Candidate03b, "option_c": oracle.Candidate03c},
"cc04_outer_cutoffs": {"option_a": oracle.Candidate04a, "option_b": oracle.Candidate04b, "option_c": oracle.Candidate04c},
"ni05_negative_then_double": {"option_a": oracle.Candidate05a, "option_b": oracle.Candidate05b, "option_c": oracle.Candidate05c},
"ni06_surcharge_discount": {"option_a": oracle.Candidate06a, "option_b": oracle.Candidate06b, "option_c": oracle.Candidate06c},
"ni07_zero_special_negative_offset": {"option_a": oracle.Candidate07a, "option_b": oracle.Candidate07b, "option_c": oracle.Candidate07c},
"ni08_upper_grade_excess": {"option_a": oracle.Candidate08a, "option_b": oracle.Candidate08b, "option_c": oracle.Candidate08c},
"lr09_compound_total": {"option_a": oracle.Candidate09a, "option_b": oracle.Candidate09b, "option_c": oracle.Candidate09c},
"lr10_floor_then_increment": {"option_a": oracle.Candidate10a, "option_b": oracle.Candidate10b, "option_c": oracle.Candidate10c},
"lr11_nonnegative_doubled_score": {"option_a": oracle.Candidate11a, "option_b": oracle.Candidate11b, "option_c": oracle.Candidate11c},
"lr12_cap_after_adjustment": {"option_a": oracle.Candidate12a, "option_b": oracle.Candidate12b, "option_c": oracle.Candidate12c},
"pr13_subtract_tripled_sum": {"option_a": oracle.Candidate13a, "option_b": oracle.Candidate13b, "option_c": oracle.Candidate13c},
"pr14_product_neighbor_factors": {"option_a": oracle.Candidate14a, "option_b": oracle.Candidate14b, "option_c": oracle.Candidate14c},
"pr15_square_minus_successor_sum": {"option_a": oracle.Candidate15a, "option_b": oracle.Candidate15b, "option_c": oracle.Candidate15c},
"pr16_composed_neighbor_product": {"option_a": oracle.Candidate16a, "option_b": oracle.Candidate16b, "option_c": oracle.Candidate16c},
"cp17_nonpositive_inclusive": {"option_a": oracle.Candidate17a, "option_b": oracle.Candidate17b, "option_c": oracle.Candidate17c},
"cp18_exact_release_code": {"option_a": oracle.Candidate18a, "option_b": oracle.Candidate18b, "option_c": oracle.Candidate18c},
"cp19_range_without_origin": {"option_a": oracle.Candidate19a, "option_b": oracle.Candidate19b, "option_c": oracle.Candidate19c},
"cp20_strict_symmetric_window": {"option_a": oracle.Candidate20a, "option_b": oracle.Candidate20b, "option_c": oracle.Candidate20c},
"bl21_saved_range_predicates": {"option_a": oracle.Candidate21a, "option_b": oracle.Candidate21b, "option_c": oracle.Candidate21c},
"bl22_reassigned_valid_flag": {"option_a": oracle.Candidate22a, "option_b": oracle.Candidate22b, "option_c": oracle.Candidate22c},
"bl23_nonzero_bounded_flag": {"option_a": oracle.Candidate23a, "option_b": oracle.Candidate23b, "option_c": oracle.Candidate23c},
"bl24_selected_nonnegative_codes": {"option_a": oracle.Candidate24a, "option_b": oracle.Candidate24b, "option_c": oracle.Candidate24c},
"tx25_sign_label": {"option_a": oracle.Candidate25a, "option_b": oracle.Candidate25b, "option_c": oracle.Candidate25c},
"tx26_state_label": {"option_a": oracle.Candidate26a, "option_b": oracle.Candidate26b, "option_c": oracle.Candidate26c},
"tx27_lexical_cutoff": {"option_a": oracle.Candidate27a, "option_b": oracle.Candidate27b, "option_c": oracle.Candidate27c},
"tx28_reassigned_text_state": {"option_a": oracle.Candidate28a, "option_b": oracle.Candidate28b, "option_c": oracle.Candidate28c},
"ob29_saturating_increment": {"option_a": oracle.Candidate29a, "option_b": oracle.Candidate29b, "option_c": oracle.Candidate29c},
"ob30_saturating_decrement": {"option_a": oracle.Candidate30a, "option_b": oracle.Candidate30b, "option_c": oracle.Candidate30c},
"ob31_saturating_double": {"option_a": oracle.Candidate31a, "option_b": oracle.Candidate31b, "option_c": oracle.Candidate31c},
"ob32_clamped_absolute": {"option_a": oracle.Candidate32a, "option_b": oracle.Candidate32b, "option_c": oracle.Candidate32c},
}
var references = map[string]func(int64) int64{
"cc01_inclusive_band": oracleRef01,
"cc02_nonzero_disjunction": oracleRef02,
"cc03_two_islands": oracleRef03,
"cc04_outer_cutoffs": oracleRef04,
"ni05_negative_then_double": oracleRef05,
"ni06_surcharge_discount": oracleRef06,
"ni07_zero_special_negative_offset": oracleRef07,
"ni08_upper_grade_excess": oracleRef08,
"lr09_compound_total": oracleRef09,
"lr10_floor_then_increment": oracleRef10,
"lr11_nonnegative_doubled_score": oracleRef11,
"lr12_cap_after_adjustment": oracleRef12,
"pr13_subtract_tripled_sum": oracleRef13,
"pr14_product_neighbor_factors": oracleRef14,
"pr15_square_minus_successor_sum": oracleRef15,
"pr16_composed_neighbor_product": oracleRef16,
"cp17_nonpositive_inclusive": oracleRef17,
"cp18_exact_release_code": oracleRef18,
"cp19_range_without_origin": oracleRef19,
"cp20_strict_symmetric_window": oracleRef20,
"bl21_saved_range_predicates": oracleRef21,
"bl22_reassigned_valid_flag": oracleRef22,
"bl23_nonzero_bounded_flag": oracleRef23,
"bl24_selected_nonnegative_codes": oracleRef24,
"tx25_sign_label": oracleRef25,
"tx26_state_label": oracleRef26,
"tx27_lexical_cutoff": oracleRef27,
"tx28_reassigned_text_state": oracleRef28,
"ob29_saturating_increment": oracleRef29,
"ob30_saturating_decrement": oracleRef30,
"ob31_saturating_double": oracleRef31,
"ob32_clamped_absolute": oracleRef32,
}

// These bridge functions expose the independent package references without sharing candidate bodies.
func oracleRef01(input int64) int64 { return oracle.Reference("cc01_inclusive_band", input) }
func oracleRef02(input int64) int64 { return oracle.Reference("cc02_nonzero_disjunction", input) }
func oracleRef03(input int64) int64 { return oracle.Reference("cc03_two_islands", input) }
func oracleRef04(input int64) int64 { return oracle.Reference("cc04_outer_cutoffs", input) }
func oracleRef05(input int64) int64 { return oracle.Reference("ni05_negative_then_double", input) }
func oracleRef06(input int64) int64 { return oracle.Reference("ni06_surcharge_discount", input) }
func oracleRef07(input int64) int64 { return oracle.Reference("ni07_zero_special_negative_offset", input) }
func oracleRef08(input int64) int64 { return oracle.Reference("ni08_upper_grade_excess", input) }
func oracleRef09(input int64) int64 { return oracle.Reference("lr09_compound_total", input) }
func oracleRef10(input int64) int64 { return oracle.Reference("lr10_floor_then_increment", input) }
func oracleRef11(input int64) int64 { return oracle.Reference("lr11_nonnegative_doubled_score", input) }
func oracleRef12(input int64) int64 { return oracle.Reference("lr12_cap_after_adjustment", input) }
func oracleRef13(input int64) int64 { return oracle.Reference("pr13_subtract_tripled_sum", input) }
func oracleRef14(input int64) int64 { return oracle.Reference("pr14_product_neighbor_factors", input) }
func oracleRef15(input int64) int64 { return oracle.Reference("pr15_square_minus_successor_sum", input) }
func oracleRef16(input int64) int64 { return oracle.Reference("pr16_composed_neighbor_product", input) }
func oracleRef17(input int64) int64 { return oracle.Reference("cp17_nonpositive_inclusive", input) }
func oracleRef18(input int64) int64 { return oracle.Reference("cp18_exact_release_code", input) }
func oracleRef19(input int64) int64 { return oracle.Reference("cp19_range_without_origin", input) }
func oracleRef20(input int64) int64 { return oracle.Reference("cp20_strict_symmetric_window", input) }
func oracleRef21(input int64) int64 { return oracle.Reference("bl21_saved_range_predicates", input) }
func oracleRef22(input int64) int64 { return oracle.Reference("bl22_reassigned_valid_flag", input) }
func oracleRef23(input int64) int64 { return oracle.Reference("bl23_nonzero_bounded_flag", input) }
func oracleRef24(input int64) int64 { return oracle.Reference("bl24_selected_nonnegative_codes", input) }
func oracleRef25(input int64) int64 { return oracle.Reference("tx25_sign_label", input) }
func oracleRef26(input int64) int64 { return oracle.Reference("tx26_state_label", input) }
func oracleRef27(input int64) int64 { return oracle.Reference("tx27_lexical_cutoff", input) }
func oracleRef28(input int64) int64 { return oracle.Reference("tx28_reassigned_text_state", input) }
func oracleRef29(input int64) int64 { return oracle.Reference("ob29_saturating_increment", input) }
func oracleRef30(input int64) int64 { return oracle.Reference("ob30_saturating_decrement", input) }
func oracleRef31(input int64) int64 { return oracle.Reference("ob31_saturating_double", input) }
func oracleRef32(input int64) int64 { return oracle.Reference("ob32_clamped_absolute", input) }

func main() {
    data, err := os.ReadFile("../testdata/vectors.json")
    if err != nil { panic(err) }
    var vectors []vector
    if err := json.Unmarshal(data, &vectors); err != nil { panic(err) }
    results := make([]designResult, 0, len(vectors))
    for index, item := range vectors {
        options := candidates[item.ID]
        optionIDs := []string{"option_a", "option_b", "option_c"}
        ordered := make([]rowResult, 0, len(item.Training))
        eval := make([]rowResult, 0, len(item.Evaluation))
        outputs := map[string][]int64{}
        evalOutputs := map[string][]int64{}
        discrimination := map[string][]int64{}
        gold := optionIDs[(3-(index%3))%3]
        for _, optionID := range optionIDs {
            outputs[optionID] = make([]int64, 0, len(item.Training))
            evalOutputs[optionID] = make([]int64, 0, len(item.Evaluation))
            discrimination[optionID] = []int64{}
        }
        for _, test := range item.Training {
            actual := references[item.ID](test.Input)
            ordered = append(ordered, rowResult{Input:test.Input, Expected:test.Expected, Actual:actual, Passed:actual==test.Expected})
            goldValue := options[gold](test.Input)
            for _, optionID := range optionIDs {
                value := options[optionID](test.Input)
                outputs[optionID] = append(outputs[optionID], value)
                if optionID != gold && value != goldValue { discrimination[optionID] = append(discrimination[optionID], test.Input) }
            }
        }
        for _, test := range item.Evaluation {
            actual := references[item.ID](test.Input)
            eval = append(eval, rowResult{Input:test.Input, Expected:test.Expected, Actual:actual, Passed:actual==test.Expected})
            for _, optionID := range optionIDs { evalOutputs[optionID] = append(evalOutputs[optionID], options[optionID](test.Input)) }
        }
        results = append(results, designResult{ID:item.ID, Training:ordered, Evaluation:eval, CandidateTrainingOutputs:outputs, CandidateEvaluationOutputs:evalOutputs, GoldCandidate:gold, DiscriminatingInputs:discrimination})
    }
    output := struct { Schema string `json:"schema"`; ModelCalls int `json:"model_calls"`; Designs []designResult `json:"designs"` }{Schema:"gooo/ir-composition-go-oracle-execution/v1", ModelCalls:0, Designs:results}
    encoder := json.NewEncoder(os.Stdout); encoder.SetIndent("", "  ")
    if err := encoder.Encode(output); err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(1) }
}
