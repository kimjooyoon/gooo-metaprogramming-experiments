package bodycodegen
import "testing"
func TestBooleanLocal(t *testing.T) { cases:=[]struct{in,want int64}{{5, 5},
{0, 0},
{9, 9},}; for _,tc:=range cases { if got:=FocusedFalse(tc.in);got!=tc.want { t.Errorf("input %d got %d want %d",tc.in,got,tc.want) } } }
