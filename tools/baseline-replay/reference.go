package main

import "math"

// A Go port of the frozen Python int64 specification. Native int64 arithmetic
// wraps after each operation; the four saturating cases have explicit bounds.
// Candidate bodies and the retained Go reference implementations are separate.
func referenceValue(id string, x int64) int64 {
	choose := func(condition bool, yes, no int64) int64 {
		if condition {
			return yes
		}
		return no
	}
	switch id {
	case "cc01_inclusive_band":
		return choose(x >= 3 && x <= 8, 2, -1)
	case "cc02_nonzero_disjunction":
		return choose(x != 0, 1, 0)
	case "cc03_two_islands":
		return choose(x == -4 || x == 4, 7, 0)
	case "cc04_outer_cutoffs":
		return choose(x <= -6 || x >= 8, 9, 0)
	case "ni05_negative_then_double":
		if x < 0 {
			return -1
		}
		if x < 10 {
			return x * 2
		}
		return 20
	case "ni06_surcharge_discount":
		if x < 0 {
			return 0
		}
		if x > 100 {
			return x - 10
		}
		return x + 10
	case "ni07_zero_special_negative_offset":
		if x < 0 {
			return x + 2
		}
		return choose(x == 0, 5, 3)
	case "ni08_upper_grade_excess":
		if x < 60 {
			return -1
		}
		if x < 80 {
			return 0
		}
		return x - 80
	case "lr09_compound_total":
		return (x + 5) * 2
	case "lr10_floor_then_increment":
		return choose(x < 0, 0, x+1)
	case "lr11_nonnegative_doubled_score":
		doubled := x * 2
		return choose(doubled >= 0, doubled+1, 0)
	case "lr12_cap_after_adjustment":
		amount := x + 3
		if amount > 10 {
			amount = 10
		}
		return amount - 1
	case "pr13_subtract_tripled_sum":
		return 100 - (x+2)*3
	case "pr14_product_neighbor_factors":
		return (x + (x + 1)) * (x - 2)
	case "pr15_square_minus_successor_sum":
		return x*x - (x + 4)
	case "pr16_composed_neighbor_product":
		return (x+1)*(x+2) - x
	case "cp17_nonpositive_inclusive":
		return choose(x <= 0, 1, 0)
	case "cp18_exact_release_code":
		return choose(x == 7, 1, 0)
	case "cp19_range_without_origin":
		return choose(x >= -3 && x <= 3 && x != 0, 1, 0)
	case "cp20_strict_symmetric_window":
		return choose(x > -5 && x < 5, 4, -4)
	case "bl21_saved_range_predicates":
		return choose(x >= -2 && x <= 2, 1, 0)
	case "bl22_reassigned_valid_flag":
		return choose(x >= 0 && x <= 5, 5, -5)
	case "bl23_nonzero_bounded_flag":
		return choose(x != 0 && x >= -4 && x <= 4, 9, 0)
	case "bl24_selected_nonnegative_codes":
		return choose(x == 2 || x == 4, 6, 0)
	case "tx25_sign_label":
		return choose(x < 0, -1, 1)
	case "tx26_state_label":
		return choose(x > 0, 1, 0)
	case "tx27_lexical_cutoff":
		return choose(x < 0, 1, 0)
	case "tx28_reassigned_text_state":
		return choose(x > 0, 2, -2)
	case "ob29_saturating_increment":
		return choose(x == math.MaxInt64, math.MaxInt64, x+1)
	case "ob30_saturating_decrement":
		return choose(x == math.MinInt64, math.MinInt64, x-1)
	case "ob31_saturating_double":
		if x > math.MaxInt64/2 {
			return math.MaxInt64
		}
		if x < math.MinInt64/2 {
			return math.MinInt64
		}
		return x * 2
	case "ob32_clamped_absolute":
		if x == math.MinInt64 {
			return math.MaxInt64
		}
		if x < 0 {
			return -x
		}
		return x
	default:
		require(false, "missing independent reference: %s", id)
		return 0
	}
}
