package http_test

import (
	"fmt"
	"testing"

	sehttp "github.com/mb-89/SE/src/modules/io/http"
)

func TestTheFakeNetKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) world {
		f := sehttp.NewFake()
		n := 0
		return world{net: f, routine: func(token string, limit int) (string, func() int) {
			n++
			url := fmt.Sprintf("https://api.example/v1/routines/r%d/fire", n)
			f.Routine(url, token, limit)
			return url, func() int { return f.Fired(url) }
		}}
	})
}

func TestTheFakeNetNamesANewSessionForEachFire(t *testing.T) {
	t.Parallel()
	f := sehttp.NewFake()
	f.Routine("https://r/fire", "tok", 2)
	a1, _ := f.Fire("https://r/fire", "tok")
	a2, _ := f.Fire("https://r/fire", "tok")
	if string(a1.Body) == string(a2.Body) {
		t.Fatalf("two fires answered the same session: %s", a1.Body)
	}
}
