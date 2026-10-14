package lib

// FakeClock is Clock's fake.
type FakeClock struct{ T int }

// Now answers the fake time.
func (f FakeClock) Now() int { return f.T }
