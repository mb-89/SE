package session_test

import (
	"testing"

	"github.com/mb-89/SE/src/modules/io/session"
)

func TestTheFakeLogKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(*testing.T) session.Log { return session.NewFake() })
}
