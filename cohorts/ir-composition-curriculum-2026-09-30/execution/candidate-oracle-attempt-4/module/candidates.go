package oracle

// Candidate functions compile each frozen Gooo body shell with a finite option.

func Candidate01a(input int64) int64 {
	if (input >= 3 && input <= 8) { return 2 } else { return -1 }
}

func Candidate01b(input int64) int64 {
	if (input > 3 && input <= 8) { return 2 } else { return -1 }
}

func Candidate01c(input int64) int64 {
	if (input >= 3 && input < 8) { return 2 } else { return -1 }
}

func Candidate02a(input int64) int64 {
	if (input < 0 && input > 0) { return 1 } else { return 0 }
}

func Candidate02b(input int64) int64 {
	if (input >= 0) { return 1 } else { return 0 }
}

func Candidate02c(input int64) int64 {
	if (input < 0 || input > 0) { return 1 } else { return 0 }
}

func Candidate03a(input int64) int64 {
	if (input < -4 || input > 4) { return 7 } else { return 0 }
}

func Candidate03b(input int64) int64 {
	if (input == -4 || input == 4) { return 7 } else { return 0 }
}

func Candidate03c(input int64) int64 {
	if (input >= -4 && input <= 4) { return 7 } else { return 0 }
}

func Candidate04a(input int64) int64 {
	if (input <= -6 || input >= 8) { return 9 } else { return 0 }
}

func Candidate04b(input int64) int64 {
	if (input <= -8 || input >= 6) { return 9 } else { return 0 }
}

func Candidate04c(input int64) int64 {
	if (input <= -6 && input >= 8) { return 9 } else { return 0 }
}

func Candidate05a(input int64) int64 {
	if input < 0 { return -1 } else { if input < 10 { return (input + 2) } else { return 20 } }
}

func Candidate05b(input int64) int64 {
	if input < 0 { return -1 } else { if input < 10 { return (input * 3) } else { return 20 } }
}

func Candidate05c(input int64) int64 {
	if input < 0 { return -1 } else { if input < 10 { return (input * 2) } else { return 20 } }
}

func Candidate06a(input int64) int64 {
	if input < 0 { return 0 } else { if input > 100 { return input - 10 } else { return (input + 11) } }
}

func Candidate06b(input int64) int64 {
	if input < 0 { return 0 } else { if input > 100 { return input - 10 } else { return (input + 10) } }
}

func Candidate06c(input int64) int64 {
	if input < 0 { return 0 } else { if input > 100 { return input - 10 } else { return (input + 9) } }
}

func Candidate07a(input int64) int64 {
	if input >= 0 { if input == 0 { return 5 } else { return 3 } } else { return (input + 2) }
}

func Candidate07b(input int64) int64 {
	if input >= 0 { if input == 0 { return 5 } else { return 3 } } else { return (input - 2) }
}

func Candidate07c(input int64) int64 {
	if input >= 0 { if input == 0 { return 5 } else { return 3 } } else { return (input + 1) }
}

func Candidate08a(input int64) int64 {
	if input < 60 { return -1 } else { if input < 80 { return 0 } else { return (input - 79) } }
}

func Candidate08b(input int64) int64 {
	if input < 60 { return -1 } else { if input < 80 { return 0 } else { return (input - 81) } }
}

func Candidate08c(input int64) int64 {
	if input < 60 { return -1 } else { if input < 80 { return 0 } else { return (input - 80) } }
}

func Candidate09a(input int64) int64 {
	var total = input + 5;
	total = total * 2;
	return (input + 10)
}

func Candidate09b(input int64) int64 {
	var total = input + 5;
	total = total * 2;
	return (total)
}

func Candidate09c(input int64) int64 {
	var total = input + 5;
	total = total * 2;
	return (input * 2 + 5)
}

func Candidate10a(input int64) int64 {
	var adjusted = input;
	if adjusted < 0 { adjusted = 0 } else { adjusted = adjusted + 1 };
	return (adjusted)
}

func Candidate10b(input int64) int64 {
	var adjusted = input;
	if adjusted < 0 { adjusted = 0 } else { adjusted = adjusted + 1 };
	return (input)
}

func Candidate10c(input int64) int64 {
	var adjusted = input;
	if adjusted < 0 { adjusted = 0 } else { adjusted = adjusted + 1 };
	return (adjusted + 1)
}

func Candidate11a(input int64) int64 {
	var score = input * 2;
	var nonnegative = score >= 0;
	if nonnegative { score = score + 1 } else { score = 0 };
	return (input * 2 + 1)
}

func Candidate11b(input int64) int64 {
	var score = input * 2;
	var nonnegative = score >= 0;
	if nonnegative { score = score + 1 } else { score = 0 };
	return (input)
}

func Candidate11c(input int64) int64 {
	var score = input * 2;
	var nonnegative = score >= 0;
	if nonnegative { score = score + 1 } else { score = 0 };
	return (score)
}

func Candidate12a(input int64) int64 {
	var amount = input;
	amount = amount + 3;
	if amount > 10 { amount = 10 } else { amount = amount };
	amount = amount - 1;
	return (amount + 1)
}

func Candidate12b(input int64) int64 {
	var amount = input;
	amount = amount + 3;
	if amount > 10 { amount = 10 } else { amount = amount };
	amount = amount - 1;
	return (amount)
}

func Candidate12c(input int64) int64 {
	var amount = input;
	amount = amount + 3;
	if amount > 10 { amount = 10 } else { amount = amount };
	amount = amount - 1;
	return (input + 2)
}

func Candidate13a(input int64) int64 {
	return 100 - (input + 2) * 3
}

func Candidate13b(input int64) int64 {
	return 100 - (input + 3) * 3
}

func Candidate13c(input int64) int64 {
	return 100 - (input - 2) * 3
}

func Candidate14a(input int64) int64 {
	return (input + (input - 1)) * (input - 2)
}

func Candidate14b(input int64) int64 {
	return (input + (input)) * (input - 2)
}

func Candidate14c(input int64) int64 {
	return (input + (input + 1)) * (input - 2)
}

func Candidate15a(input int64) int64 {
	return input * input - (input - 4)
}

func Candidate15b(input int64) int64 {
	return input * input - (input + 4)
}

func Candidate15c(input int64) int64 {
	return input * input - (input + 2)
}

func Candidate16a(input int64) int64 {
	var next = input + 1;
	return next * (input + 2) - input
}

func Candidate16b(input int64) int64 {
	var next = input + 1;
	return next * (input + 1) - input
}

func Candidate16c(input int64) int64 {
	var next = input + 1;
	return next * (input + 3) - input
}

func Candidate17a(input int64) int64 {
	if (input < 0) { return 1 } else { return 0 }
}

func Candidate17b(input int64) int64 {
	if (input == 0) { return 1 } else { return 0 }
}

func Candidate17c(input int64) int64 {
	if (input <= 0) { return 1 } else { return 0 }
}

func Candidate18a(input int64) int64 {
	if (input == 8) { return 1 } else { return 0 }
}

func Candidate18b(input int64) int64 {
	if (input == 7) { return 1 } else { return 0 }
}

func Candidate18c(input int64) int64 {
	if (input >= 7) { return 1 } else { return 0 }
}

func Candidate19a(input int64) int64 {
	if (input >= -3 && input <= 3 && input != 0) { return 1 } else { return 0 }
}

func Candidate19b(input int64) int64 {
	if (input >= -3 && input <= 3) { return 1 } else { return 0 }
}

func Candidate19c(input int64) int64 {
	if (input < -3 || input > 3) { return 1 } else { return 0 }
}

func Candidate20a(input int64) int64 {
	if (input >= -5 && input <= 5) { return 4 } else { return -4 }
}

func Candidate20b(input int64) int64 {
	if (input > -5 && input <= 5) { return 4 } else { return -4 }
}

func Candidate20c(input int64) int64 {
	if (input > -5 && input < 5) { return 4 } else { return -4 }
}

func Candidate21a(input int64) int64 {
	var low = input >= -2;
	var high = input <= 2;
	var allowed = low && high;
	_ = allowed
	if (low && input == 0) { return 1 } else { return 0 }
}

func Candidate21b(input int64) int64 {
	var low = input >= -2;
	var high = input <= 2;
	var allowed = low && high;
	if (allowed) { return 1 } else { return 0 }
}

func Candidate21c(input int64) int64 {
	var low = input >= -2;
	var high = input <= 2;
	var allowed = low && high;
	_ = allowed
	if (low || high) { return 1 } else { return 0 }
}

func Candidate22a(input int64) int64 {
	var valid = input >= 0;
	valid = valid && input <= 5;
	if (valid) { return 5 } else { return -5 }
}

func Candidate22b(input int64) int64 {
	var valid = input >= 0;
	valid = valid && input <= 5;
	if (valid || input == 10) { return 5 } else { return -5 }
}

func Candidate22c(input int64) int64 {
	var valid = input >= 0;
	valid = valid && input <= 5;
	if (input <= 5) { return 5 } else { return -5 }
}

func Candidate23a(input int64) int64 {
	var nonzero = input != 0;
	var bounded = input >= -4 && input <= 4;
	if (nonzero || bounded) { return 9 } else { return 0 }
}

func Candidate23b(input int64) int64 {
	var nonzero = input != 0;
	var bounded = input >= -4 && input <= 4;
	_ = bounded
	if (nonzero) { return 9 } else { return 0 }
}

func Candidate23c(input int64) int64 {
	var nonzero = input != 0;
	var bounded = input >= -4 && input <= 4;
	if (nonzero && bounded) { return 9 } else { return 0 }
}

func Candidate24a(input int64) int64 {
	var selected = input == 2;
	if input < 0 { selected = false } else { selected = selected || input == 4 };
	if (input == 2) { return 6 } else { return 0 }
}

func Candidate24b(input int64) int64 {
	var selected = input == 2;
	if input < 0 { selected = false } else { selected = selected || input == 4 };
	if (selected) { return 6 } else { return 0 }
}

func Candidate24c(input int64) int64 {
	var selected = input == 2;
	if input < 0 { selected = false } else { selected = selected || input == 4 };
	if (selected && input != 4) { return 6 } else { return 0 }
}

func Candidate25a(input int64) int64 {
	var label = "neutral";
	if input < 0 { label = "negative" } else { label = "nonnegative" };
	if label == ("negative") { return -1 } else { return 1 }
}

func Candidate25b(input int64) int64 {
	var label = "neutral";
	if input < 0 { label = "negative" } else { label = "nonnegative" };
	if label == ("nonnegative") { return -1 } else { return 1 }
}

func Candidate25c(input int64) int64 {
	var label = "neutral";
	if input < 0 { label = "negative" } else { label = "nonnegative" };
	if label == ("neutral") { return -1 } else { return 1 }
}

func Candidate26a(input int64) int64 {
	var status = "pending";
	if input == 0 { status = "closed" } else { if input > 0 { status = "open" } else { status = "error" } };
	if status == ("closed") { return 1 } else { return 0 }
}

func Candidate26b(input int64) int64 {
	var status = "pending";
	if input == 0 { status = "closed" } else { if input > 0 { status = "open" } else { status = "error" } };
	if status == ("error") { return 1 } else { return 0 }
}

func Candidate26c(input int64) int64 {
	var status = "pending";
	if input == 0 { status = "closed" } else { if input > 0 { status = "open" } else { status = "error" } };
	if status == ("open") { return 1 } else { return 0 }
}

func Candidate27a(input int64) int64 {
	var label = "plum";
	if input < 0 { label = "amber" } else { label = "zinc" };
	if label < ("zoo") { return 1 } else { return 0 }
}

func Candidate27b(input int64) int64 {
	var label = "plum";
	if input < 0 { label = "amber" } else { label = "zinc" };
	if label < ("gold") { return 1 } else { return 0 }
}

func Candidate27c(input int64) int64 {
	var label = "plum";
	if input < 0 { label = "amber" } else { label = "zinc" };
	if label < ("amber") { return 1 } else { return 0 }
}

func Candidate28a(input int64) int64 {
	var status = "idle" + "-pending";
	if input > 0 { status = "ready" } else { status = status };
	if status == ("ready") { return 2 } else { return -2 }
}

func Candidate28b(input int64) int64 {
	var status = "idle" + "-pending";
	if input > 0 { status = "ready" } else { status = status };
	if status == ("idle-pending") { return 2 } else { return -2 }
}

func Candidate28c(input int64) int64 {
	var status = "idle" + "-pending";
	if input > 0 { status = "ready" } else { status = status };
	if status == ("done") { return 2 } else { return -2 }
}

func Candidate29a(input int64) int64 {
	if input == 9223372036854775807 { return input } else { return (input) }
}

func Candidate29b(input int64) int64 {
	if input == 9223372036854775807 { return input } else { return (input - 1) }
}

func Candidate29c(input int64) int64 {
	if input == 9223372036854775807 { return input } else { return (input + 1) }
}

func Candidate30a(input int64) int64 {
	if input == (-9223372036854775807 - 1) { return input } else { return (input + 1) }
}

func Candidate30b(input int64) int64 {
	if input == (-9223372036854775807 - 1) { return input } else { return (input - 1) }
}

func Candidate30c(input int64) int64 {
	if input == (-9223372036854775807 - 1) { return input } else { return (input) }
}

func Candidate31a(input int64) int64 {
	if input > 4611686018427387903 { return 9223372036854775807 } else { if input < (-4611686018427387903 - 1) { return (-9223372036854775807 - 1) } else { return (input * 2) } }
}

func Candidate31b(input int64) int64 {
	if input > 4611686018427387903 { return 9223372036854775807 } else { if input < (-4611686018427387903 - 1) { return (-9223372036854775807 - 1) } else { return (input * 3) } }
}

func Candidate31c(input int64) int64 {
	if input > 4611686018427387903 { return 9223372036854775807 } else { if input < (-4611686018427387903 - 1) { return (-9223372036854775807 - 1) } else { return (input + 2) } }
}

func Candidate32a(input int64) int64 {
	var magnitude = input;
	if input < 0 { magnitude = 0 - magnitude } else { magnitude = input };
	if input == (-9223372036854775807 - 1) { return 9223372036854775807 } else { return (input) }
}

func Candidate32b(input int64) int64 {
	var magnitude = input;
	if input < 0 { magnitude = 0 - magnitude } else { magnitude = input };
	if input == (-9223372036854775807 - 1) { return 9223372036854775807 } else { return (0 - magnitude) }
}

func Candidate32c(input int64) int64 {
	var magnitude = input;
	if input < 0 { magnitude = 0 - magnitude } else { magnitude = input };
	if input == (-9223372036854775807 - 1) { return 9223372036854775807 } else { return (magnitude) }
}
